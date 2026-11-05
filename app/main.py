import asyncio
import logging
import uuid
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app import services

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)
app = FastAPI(title='Incident Response Agent')
frontend = Path(__file__).resolve().parent.parent / 'frontend'
app.mount('/static', StaticFiles(directory=frontend), name='static')


class TriageRequest(BaseModel):
    alert: str = Field(min_length=5, max_length=12000)
    memory: bool = True


class FeedbackRequest(BaseModel):
    alert: str = Field(min_length=5, max_length=12000)
    suggestion: services.Answer
    worked: bool
    notes: str = Field(max_length=4000, default='')


@app.get('/')
def index():
    return FileResponse(frontend / 'index.html')


@app.post('/api/triage')
async def triage(req: TriageRequest):
    if not req.alert.strip() or len(req.alert.strip()) < 5:
        raise HTTPException(422, 'Alert must contain at least 5 non-whitespace characters.')
    memories, warning = await services.recall(req.alert) if req.memory else ([], None)
    try:
        response = await asyncio.to_thread(services.answer, req.alert, memories)
    except Exception as exc:
        log.exception('Triage failed')
        raise HTTPException(502, str(exc) if isinstance(exc, RuntimeError) else 'Triage failed; please retry.') from exc
    return {'answer': response, 'memories': memories, 'memory_warning': warning, 'memory_enabled': req.memory}


@app.post('/api/feedback')
async def feedback(req: FeedbackRequest):
    incident_id = 'feedback-' + uuid.uuid4().hex[:12]
    content = (f'Incident {incident_id}. Alert: {req.alert}\n'
               f'Suggested root cause: {req.suggestion.likely_root_cause}\n'
               f'Suggested fix steps: {"; ".join(req.suggestion.recommended_fix_steps)}\n'
               f'Engineer outcome: {"WORKED" if req.worked else "FAILED"}. '
               f'Engineer notes: {req.notes or "No notes provided"}. '
               'This is engineer feedback on a suggestion, not independently verified root cause.')
    try:
        await services.retain(content)
    except Exception as exc:
        log.exception('Feedback retain failed')
        raise HTTPException(503, 'Could not save feedback to Hindsight. Please retry.') from exc
    return {'status': 'retained', 'incident_id': incident_id}
