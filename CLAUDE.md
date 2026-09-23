# pdf2video — notes for AI coding sessions

**Read `docs/HANDOFF.md` first.** It is the living status doc: what is live, what each step costs, env vars, how to deploy, known risks, and the next ideas. `docs/MIGRATION_PLAN.md` holds the architecture, the HTTP API, and the (completed) migration checklist.

## Branches and deploys
- `main` is current (PR #45 merged 2026-09-23). Every push to `main` auto-deploys production at https://pdf2video-wine.vercel.app. Other branches get preview deployments.
- The Vercel CLI on the owner's Mac is logged in; `vercel deploy --prod` also works.

## Layout
- `app/main.py` — FastAPI app, static mount, router include. `vercel.json` points the `api` service at `app.main:app`.
- `app/routers/jobs.py` — every endpoint is one bounded unit of work (must finish well under Vercel's 300 s cap) and persists its result before returning.
- `app/services/` — thin vendor clients: `pdf_text` (pypdf), `ocr_service` (Mistral, fallback only), `planning_service` + `manim_service` (Anthropic, async, Opus 5), `kodisc_service` (submit/check), `elevenlabs_service`, `r2_service` (private bucket, presigned URLs), `shotstack_service` (submit/check), `safe_slide_template` (tier-3 fallback), `manim_validator` (AST checks, never executes code).
- `app/store.py` — job persistence, one JSON document per job. SQLite locally, Postgres via `DATABASE_URL` (or `POSTGRES_URL`) on Vercel.
- `app/models/schemas.py` — `PresentationPlan` (Claude's structured output) and the `Job` document.
- `static/` — vanilla JS. `app.js` sequences the steps and can resume any job by id (`?job=<id>`).
- `tests/` — pytest with every vendor faked in `conftest.py`. `pytest` runs offline in under a second.

## Rules that keep it deployable on Vercel
- Never write to the repo directory at runtime. Only `/tmp` is writable and it does not persist.
- Never keep job state in module-level dicts. Read and write through `deps.store`.
- Never block the event loop: `AsyncAnthropic`, async httpx, `asyncio.to_thread` for boto3.
- No background tasks that outlive the request. Long vendor work is submit-then-poll, one poll per request.
- No ffmpeg. Generated Manim scenes end on their final frame; Shotstack holds that frame under the narration.
- Generated code is validated by AST only. Never `exec` LLM output.
- R2 objects stay private. Store the object key; mint a presigned URL on every read.

## Commands
```
python -m venv .venv && source .venv/bin/activate && pip install -r requirements-dev.txt
cp .env.example .env            # fill in keys; leave DATABASE_URL unset to use SQLite
uvicorn app.main:app --reload   # http://localhost:8000
pytest
vercel deploy                   # preview
vercel deploy --prod
vercel env pull .env.local --environment=production   # production secrets for local testing (gitignored)
```
