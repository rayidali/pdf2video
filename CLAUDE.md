# pdf2video — notes for AI coding sessions

**Read `docs/HANDOFF.md` first.** It is the living status doc: what is done, what is next, what env vars exist, and how to deploy. `docs/MIGRATION_PLAN.md` holds the target architecture and the step checklist.

## Branches
- `vercel-migration` — active work. Based on the Kodisc v2 fix (PR #44). Merge this into `main` when the Vercel deploy is verified.
- `main` — stale. Still targets Kodisc's removed v1 API. Do not build on it.

## Layout
- `app/main.py` — FastAPI app, static mount, router include. Vercel auto-detects `app/main.py` as the entrypoint.
- `app/routers/` — HTTP endpoints. Each endpoint does one bounded unit of work (must finish well under 300 s).
- `app/services/` — thin clients for Mistral OCR, Anthropic, Kodisc, ElevenLabs, Cloudflare R2, Shotstack.
- `app/store.py` — job persistence. One JSON document per job. SQLite locally, Postgres (`DATABASE_URL`) on Vercel.
- `static/` — vanilla JS frontend. The browser drives the pipeline step by step and can resume a job by id.
- `docs/` — handoff and plan.

## Rules that keep it deployable on Vercel
- Never write to the repo directory at runtime. Only `/tmp` is writable, and it does not persist.
- Never keep job state in module-level dicts. Read and write through `JobStore`.
- Never block the event loop: use `AsyncAnthropic`, async httpx, and `asyncio.to_thread` for boto3.
- No background tasks that outlive the request. Long vendor work is submit-then-poll, one poll per request.
- No ffmpeg. Generated Manim scenes end on their final frame so nothing needs trimming.

## Commands
```
python -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt
cp .env.example .env   # fill in keys
uvicorn app.main:app --reload
pytest
vercel deploy          # preview
vercel deploy --prod
```
