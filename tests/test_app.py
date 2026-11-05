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
    mock_client.arecall.assert_awaited_once_with(bank_id=services.bank(), query='pool timeout', max_tokens=1200, budget='mid', include_chunks=False)
    assert warning is None
    assert memories == [{'id': 'fact-1', 'text': 'Rollback worked', 'source': None}]


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


def test_recall_limits_memories(monkeypatch):
    from types import SimpleNamespace
    rows = [SimpleNamespace(id=str(i), text='x' * 600) for i in range(8)]
    mock_client = SimpleNamespace(arecall=AsyncMock(return_value=SimpleNamespace(results=rows)))
    monkeypatch.setattr(services, 'memory_client', lambda: mock_client)
    memories, _ = asyncio.run(services.recall('pool timeout'))
    assert len(memories) == 5
    assert all(len(item['text']) == 400 for item in memories)
    assert mock_client.arecall.await_args.kwargs['include_chunks'] is False


def setup_groq(monkeypatch, responses):
    from types import SimpleNamespace
    from unittest.mock import Mock
    monkeypatch.setenv('GROQ_API_KEY', 'test-key')
    monkeypatch.setenv('GROQ_PRIMARY_MODEL', 'primary-test')
    monkeypatch.setenv('GROQ_FALLBACK_MODEL', 'fallback-test')
    create = Mock(side_effect=responses)
    monkeypatch.setattr(services, 'OpenAI', lambda **kwargs: SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create))))
    return create


def completion(text):
    from types import SimpleNamespace
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=text))])


def api_error(status, message):
    class Error(Exception):
        status_code = status
    return Error(message)


def test_groq_json_fence_and_retry(monkeypatch):
    import json
    create = setup_groq(monkeypatch, [completion('not json'), completion('```json\n' + json.dumps(ANSWER) + '\n```')])
    assert services.answer('pool timeout', []) == ANSWER
    assert create.call_count == 2
    assert 'only a valid JSON object' in create.call_args.kwargs['messages'][-1]['content']


def test_groq_format_rejection_and_prompt_limit(monkeypatch):
    import json
    create = setup_groq(monkeypatch, [api_error(400, 'response_format json_object unsupported'), completion(json.dumps(ANSWER))])
    services.answer('pool timeout', [{'id': str(i), 'text': 'x' * 500, 'source': 'long'} for i in range(6)])
    assert 'response_format' in create.call_args_list[0].kwargs
    assert 'response_format' not in create.call_args_list[1].kwargs
    assert create.call_args_list[1].kwargs['model'] == 'primary-test'
    payload = json.loads(create.call_args.kwargs['messages'][1]['content'])
    assert len(payload['memories']) == 5
    assert all(len(m['text']) == 400 and 'source' not in m for m in payload['memories'])


def test_groq_rate_limit_then_fallback(monkeypatch):
    import json
    waits = []
    monkeypatch.setattr(services.time, 'sleep', waits.append)
    create = setup_groq(monkeypatch, [api_error(429, 'rate limited'), api_error(429, 'still limited'), completion(json.dumps(ANSWER))])
    assert services.answer('pool timeout', []) == ANSWER
    assert [call.kwargs['model'] for call in create.call_args_list] == ['primary-test', 'primary-test', 'fallback-test']
    assert waits == [1]


def test_groq_error_reason_is_shown_in_triage(monkeypatch, caplog):
    create = setup_groq(monkeypatch, [api_error(404, 'specific primary failure'), api_error(404, 'specific fallback failure')])
    response = client.post('/api/triage', json={'alert': 'pool timeout', 'memory': False})
    assert response.status_code == 502
    assert 'model not found' in response.json()['detail']
    assert 'primary-test' in response.json()['detail'] and 'fallback-test' in response.json()['detail']
    assert 'specific primary failure' in caplog.text and 'specific fallback failure' in caplog.text
    assert create.call_count == 2
