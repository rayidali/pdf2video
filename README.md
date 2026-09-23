# Paper to Video

Drop in a research paper PDF, get back a narrated, animated explainer video in the style of 3Blue1Brown.

**Live demo:** https://pdf2video-wine.vercel.app

![CI](https://github.com/rayidali/pdf2video/actions/workflows/ci.yml/badge.svg)

## How it works

```
PDF ─▶ Mistral OCR ─▶ Claude Opus 5 ─▶ 11-slide plan (structured output)
                                            │
                       for each slide:      ▼
                       Claude writes a Manim scene ─▶ Kodisc renders it to mp4
                       ElevenLabs narrates the script ─▶ mp3 on Cloudflare R2
                                            │
                                            ▼
                       Shotstack stitches clips + narration ─▶ final mp4
```

**Three-tier rendering.** LLM-written animation code fails sometimes. Each slide gets up to three attempts: Claude writes the scene from the plan; if the renderer reports an error, Claude gets the error and fixes the code; if that fails too, a deterministic text slide built from the plan's fallback copy is rendered instead. A video always comes out.

**Serverless-shaped pipeline.** The backend runs as a single FastAPI function on Vercel. Every request does one bounded unit of work and saves its result, so the browser sequences the steps and any job can be resumed by id after a closed tab or a redeploy. Long vendor work is submit-then-poll, never a background task.

## Stack

FastAPI · Pydantic · Anthropic SDK (Opus 5, structured outputs) · Mistral OCR · Kodisc v2 · ElevenLabs · Cloudflare R2 · Shotstack · Postgres (Vercel Marketplace) · vanilla JS

## Run locally

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env        # fill in the keys
uvicorn app.main:app --reload
open http://localhost:8000
pytest                       # offline: every vendor is faked
```

Without `DATABASE_URL` the app uses a local SQLite file.

## Deploy

```bash
npm i -g vercel && vercel login
vercel link                  # creates the project
vercel env add ANTHROPIC_API_KEY   # repeat for each key in .env.example
vercel deploy --prod
```

Then add a Postgres database from the Vercel dashboard (Storage → Marketplace); it injects `DATABASE_URL`. Set `RUN_PASSCODE` so strangers cannot spend your API credits, and `SAMPLE_VIDEOS` to show finished videos on the landing page.

## API

| Method | Path | Does |
|---|---|---|
| POST | `/api/jobs` | upload PDF, run OCR |
| POST | `/api/jobs/{id}/plan` | Claude writes the slide plan |
| POST | `/api/jobs/{id}/slides/{n}/render` | Claude writes Manim, Kodisc starts rendering |
| GET | `/api/jobs/{id}/slides/{n}` | one render status check; escalates tier on failure |
| POST | `/api/jobs/{id}/voice/{n}` | ElevenLabs narration, uploaded to R2 |
| POST | `/api/jobs/{id}/assemble` | submit the Shotstack edit |
| GET | `/api/jobs/{id}/assemble` | one assembly status check |
| GET | `/api/jobs/{id}` | full job document |

## Project layout

```
app/main.py          FastAPI entrypoint (Vercel auto-detects it)
app/routers/jobs.py  the step endpoints
app/services/        thin vendor clients
app/store.py         SQLite / Postgres job store
app/models/          Pydantic schemas (plan + job document)
static/              frontend
tests/               pytest with faked vendors
docs/                handoff notes and migration plan
```

MIT License.
