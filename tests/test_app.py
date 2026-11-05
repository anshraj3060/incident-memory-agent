import asyncio
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient
from app.main import app
from app import services
from seed.seed import incidents

client = TestClient(app)
ANSWER = {'likely_root_cause': 'pool leak', 'recommended_fix_steps': ['roll back'], 'confidence': 'medium', 'based_on': []}


def test_triage_without_memory(monkeypatch):
    monkeypatch.setattr(services, 'recall', lambda _: (_ for _ in ()).throw(AssertionError('must not recall')))
    monkeypatch.setattr(services, 'answer', lambda alert, memories: ANSWER)
    response = client.post('/api/triage', json={'alert': 'pool timeout', 'memory': False})
    assert response.status_code == 200
    assert response.json()['memories'] == []


def test_memory_failure_degrades(monkeypatch):
    monkeypatch.setattr(services, 'memory_client', lambda: (_ for _ in ()).throw(TimeoutError()))
    monkeypatch.setattr(services, 'answer', lambda alert, memories: ANSWER)
    response = client.post('/api/triage', json={'alert': 'pool timeout'})
    assert response.status_code == 200
    assert 'unavailable' in response.json()['memory_warning']


def test_feedback_includes_failure(monkeypatch):
    saved = []
    async def save(content):
        saved.append(content)
    monkeypatch.setattr(services, 'retain', save)
    response = client.post('/api/feedback', json={'alert': 'pool timeout', 'suggestion': ANSWER, 'worked': False, 'notes': 'rollback did not help'})
    assert response.status_code == 200
    assert 'FAILED' in saved[0] and 'rollback did not help' in saved[0]


def test_feedback_failure_and_validation(monkeypatch):
    monkeypatch.setattr(services, 'retain', AsyncMock(side_effect=TimeoutError()))
    assert client.post('/api/feedback', json={'alert': 'pool timeout', 'suggestion': ANSWER, 'worked': True}).status_code == 503
    assert client.post('/api/triage', json={'alert': '  '}).status_code == 422


def test_seed_fields():
    rows = incidents()
    assert len(rows) == 25
    assert all({'incident_id', 'service', 'error_log', 'severity', 'root_cause', 'resolution_steps', 'runbook', 'time_to_resolve_minutes', 'date', 'outcome'} <= row.keys() for row in rows)


def test_recall_returns_facts_and_source_chunks(monkeypatch):
    from types import SimpleNamespace
    class Client:
        arecall = AsyncMock(return_value=SimpleNamespace(results=[SimpleNamespace(id='fact-1', text='Rollback worked', chunk_id='chunk-1')], chunks={'chunk-1': SimpleNamespace(text='Incident SYN-001: rollback worked')}))
    mock_client = Client()
    monkeypatch.setattr(services, 'memory_client', lambda: mock_client)
    memories, warning = asyncio.run(services.recall('pool timeout'))
    mock_client.arecall.assert_awaited_once_with(bank_id=services.bank(), query='pool timeout', max_tokens=4096, budget='mid', include_chunks=True, max_chunk_tokens=2000)
    assert warning is None
    assert memories == [{'id': 'fact-1', 'text': 'Rollback worked', 'source': 'Incident SYN-001: rollback worked'}]


def test_triage_and_feedback_await_client(monkeypatch):
    from types import SimpleNamespace
    memory = SimpleNamespace(
        arecall=AsyncMock(return_value=SimpleNamespace(results=[], chunks={})),
        aretain=AsyncMock(),
    )
    monkeypatch.setattr(services, 'memory_client', lambda: memory)
    monkeypatch.setattr(services, 'answer', lambda alert, memories: ANSWER)
    assert client.post('/api/triage', json={'alert': 'pool timeout'}).status_code == 200
    memory.arecall.assert_awaited_once()
    assert client.post('/api/feedback', json={'alert': 'pool timeout', 'suggestion': ANSWER, 'worked': True}).status_code == 200
    memory.aretain.assert_awaited_once()
