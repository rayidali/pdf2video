# Paper to Video

Drop in a research paper PDF, get back a narrated, animated explainer video in the style of 3Blue1Brown.

**Live demo:** https://pdf2video-wine.vercel.app — the landing page plays a finished video made from *Attention Is All You Need*. Running a new paper takes about 17 minutes and needs the owner's passcode, because every run spends real API credits.

![CI](https://github.com/rayidali/pdf2video/actions/workflows/ci.yml/badge.svg)

## How it works

```
PDF ─▶ pypdf text (OCR only if scanned) ─▶ Claude Opus 5 ─▶ 11-slide plan (structured output)
                                                 │
                        for each slide:          ▼
                        Claude writes a Manim scene ─▶ Kodisc renders it to mp4
                        ElevenLabs narrates the script ─▶ mp3 in Cloudflare R2
                                                 │
                                                 ▼
                        Shotstack stitches clips + narration ─▶ final mp4, copied into R2
```

**Three-tier rendering.** LLM-written animation code sometimes fails. Each slide gets up to three attempts: Claude writes the scene from the plan; if the renderer reports an error, Claude sees the error and fixes the code; if that fails too, a deterministic text slide built from the plan's fallback copy is rendered. A video always comes out.

**Serverless-shaped pipeline.** The backend is a single FastAPI function on Vercel. Every request does one bounded unit of work and saves its result to Postgres, so the browser sequences the steps and any job can be resumed by id after a closed tab or a redeploy. Long vendor work is submit-then-poll, never a background task. No ffmpeg: generated scenes hold their final frame and Shotstack holds it under the narration.

## Stack

FastAPI · Pydantic · Anthropic SDK (Claude Opus 5, structured outputs) · pypdf · Kodisc v2 (Manim rendering) · ElevenLabs · Cloudflare R2 (private, presigned URLs) · Shotstack · Neon Postgres via the Vercel Marketplace · vanilla JS

## Cost

Measured on the demo paper: about $1.25 per paper in Anthropic usage, with Kodisc, ElevenLabs and Shotstack inside their free allowances. Details in `docs/HANDOFF.md`.

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
vercel link                              # creates or links the project
vercel integration add neon --plan free_v3   # free Postgres, injects DATABASE_URL
vercel env add ANTHROPIC_API_KEY         # repeat for each key in .env.example
vercel deploy --prod
```

Set `RUN_PASSCODE` so strangers cannot spend your API credits, and `SAMPLE_VIDEOS` to show finished videos on the landing page. In the Vercel dashboard set Deployment Protection to *Standard* so production is public.

## API

| Method | Path | Does |
|---|---|---|
| POST | `/api/jobs` | upload PDF, extract text |
| POST | `/api/jobs/{id}/plan` | Claude writes the slide plan |
| POST | `/api/jobs/{id}/slides/{n}/render` | Claude writes Manim, Kodisc starts rendering |
| GET | `/api/jobs/{id}/slides/{n}` | one render status check; escalates tier on failure |
| POST | `/api/jobs/{id}/voice/{n}` | ElevenLabs narration, stored in R2 |
| POST | `/api/jobs/{id}/assemble` | submit the Shotstack edit |
| GET | `/api/jobs/{id}/assemble` | one assembly status check; stores the final mp4 |
| GET | `/api/jobs/{id}` | full job document |

## Project layout

```
app/main.py            FastAPI entrypoint
app/routers/jobs.py    the step endpoints
app/services/          thin vendor clients + pypdf extraction + tier-3 slide template
app/store.py           SQLite / Postgres job store
app/models/            Pydantic schemas (plan + job document)
static/                frontend
tests/                 pytest with faked vendors
docs/                  handoff notes and architecture
```

MIT License.
