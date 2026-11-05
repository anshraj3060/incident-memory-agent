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
    monkeypatch.setattr(services, 'retain', saved.append)
    response = client.post('/api/feedback', json={'alert': 'pool timeout', 'suggestion': ANSWER, 'worked': False, 'notes': 'rollback did not help'})
    assert response.status_code == 200
    assert 'FAILED' in saved[0] and 'rollback did not help' in saved[0]


def test_feedback_failure_and_validation(monkeypatch):
    monkeypatch.setattr(services, 'retain', lambda _: (_ for _ in ()).throw(TimeoutError()))
    assert client.post('/api/feedback', json={'alert': 'pool timeout', 'suggestion': ANSWER, 'worked': True}).status_code == 503
    assert client.post('/api/triage', json={'alert': '  '}).status_code == 422


def test_seed_fields():
    rows = incidents()
    assert len(rows) == 25
    assert all({'incident_id', 'service', 'error_log', 'severity', 'root_cause', 'resolution_steps', 'runbook', 'time_to_resolve_minutes', 'date', 'outcome'} <= row.keys() for row in rows)
