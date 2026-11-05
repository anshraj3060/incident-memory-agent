# Incident Memory Agent

An on-call assistant that compares a generic Groq response with one grounded in recalled Hindsight incident history. Engineers can record whether either suggestion worked. The memory panel shows the actual retrieved facts and source chunks supplied to the model, with cited IDs marked. Synthetic records and feedback are not verified operational truth. Always review suggestions before acting.

## Architecture

```text
Browser ── alert ──> FastAPI ── recall ──> Hindsight Cloud (incident bank)
                        │                         ▲
                        ├── alert + facts ──> Groq│
                        │                         │ retain
Browser <── answers + retrieved facts ────────────┘
Browser ── worked/failed + notes ──> FastAPI ─────┘
```

Hindsight extracts and indexes facts from retained reports. On triage, `recall` retrieves relevant facts and source chunks; both go to the LLM, which is instructed to prefer relevant successful fixes, avoid failed ones and cite only retrieved IDs. Feedback is retained with the original alert, suggested fix and outcome; it can influence later recalls but ranking and learning are not guaranteed. `reflect` exists in the SDK but is not needed here. Inspired by the self-driving-agents pattern of persistent memory and learning from outcomes.

## Setup

Requires Python 3.11+, a Groq API key, and a Hindsight Cloud account with API URL and key. Calls use credits. From the project root:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Edit .env: GROQ_API_KEY, HINDSIGHT_API_KEY, HINDSIGHT_BASE_URL
python seed.py
uvicorn app.main:app --reload
```

Open http://127.0.0.1:8000. `HINDSIGHT_BANK_ID` defaults to `incident-agent`; set a different bank to isolate a demo. Use the Cloud API base URL from your Hindsight account, not the web UI URL. The seed sends 25 synthetic reports in five synchronous batches; rerunning it can create duplicates and incurs additional cost. Indexing can take time. Never put secrets in alerts or logs: their content is sent to Hindsight and Groq.

## Demo

1. Load the example or paste an alert. With comparison checked, run triage to see generic and memory-backed answers side by side. Uncheck it for only the memory-backed answer.
2. Inspect the exact recalled facts and optional source context. A cited marker means the model referenced that retrieved ID; it is not a guarantee of factual accuracy.
3. Add notes and select worked or didn't work on an answer. Feedback is only reported saved after Hindsight accepts it.
4. Start the scenario to replay five related alerts. The first offers a generic comparison, and later steps use memory. Add feedback between incidents to demonstrate learning. This writes to the configured bank; no outcomes are invented or automatically applied. Results may not improve monotonically, and a pre-seeded bank may provide memory on the first incident.

## Reliability and API notes

The app uses the documented `hindsight-client` `Hindsight(base_url=..., api_key=..., timeout=...)`, `retain_batch(bank_id=..., items=..., retain_async=False)`, `retain(bank_id=..., content=..., context=..., retain_async=False)` and `recall(bank_id=..., query=..., include_chunks=True, ...)`. Hindsight recall failure or no results is visible and triage continues without evidence. Feedback failures are surfaced for retry. Groq uses JSON mode with validation and two attempts per model, falling back from `openai/gpt-oss-120b` to `qwen/qwen3-32b`. Model availability and Cloud permissions depend on the account. No real services are changed by this app. It has no authentication; run it locally or put it behind an authenticated gateway before exposing it.

Run tests: `python -m pytest -q` (mocked external services; no credentials needed). API docs are at `/docs`.

References: [Hindsight Python SDK](https://hindsight.vectorize.io/sdks/python), [Hindsight](https://github.com/vectorize-io/hindsight), [self-driving-agents](https://github.com/vectorize-io/self-driving-agents).
