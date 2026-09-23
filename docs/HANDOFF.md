# Handoff — pdf2video Vercel migration

_Last updated: 2026-09-23 by Claude (session 1)._ Update this file whenever a step in `MIGRATION_PLAN.md` changes state.

## Status
- Working branch: `vercel-migration` (from the Kodisc v2 fix in PR #44). Nothing merged to `main` yet.
- Old Render.com host is gone. No live URL currently exists.
- Local verification done: the v2 fix compiles, boots, and matches Kodisc's public API (`POST https://kodisc.com/api/v2/render`, Bearer `kdsc_live_…` keys).
- Migration steps 0–1 complete. See the checklist in `MIGRATION_PLAN.md`.

## Decisions made
| Decision | Why |
|---|---|
| Stay on Python/FastAPI, host on Vercel Hobby | User wants Vercel and free hosting. Vercel runs FastAPI natively on Fluid Compute. |
| Browser drives the pipeline, one short request per step | No background tasks survive on serverless. Each step is bounded and independently retryable. Job is resumable by id if the tab closes. |
| One JSON document per job in Postgres | Simplest persistence that survives restarts; free tier on the Marketplace. SQLite locally with the same interface. |
| Drop ffmpeg entirely | The trim existed only to cut a fade-to-black tail. In v2 we author the Manim code, so scenes end on the final frame and Shotstack holds that frame under the voiceover. |
| Claude Opus 5 with structured outputs for planning and code | Removes the hand-rolled JSON repair. Sonnet 5 is the cheaper switch if latency or cost bite. |
| Polling, not webhooks, for Kodisc and Shotstack (for now) | Works without a public callback URL and without signature docs. Webhooks are a later optimization. |
| Passcode gate + sample gallery | A resume link gets clicked by strangers. The gate stops credit drain; the gallery gives recruiters something instant to watch. |

## Environment variables (set in Vercel → Project → Settings → Environment Variables, or `vercel env add`)
| Name | Required | Notes |
|---|---|---|
| `ANTHROPIC_API_KEY` | yes | Planning + Manim generation |
| `MISTRAL_API_KEY` | yes | OCR |
| `KODISC_API_KEY` | yes | must start with `kdsc_live_` (regenerate at kodisc.com; old `kodisc_` keys are dead) |
| `ELEVENLABS_API_KEY` | yes | TTS. `ELEVENLABS_VOICE_ID`, `ELEVENLABS_MODEL_ID` optional |
| `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_ENDPOINT_URL`, `R2_BUCKET_NAME`, `R2_PUBLIC_URL_BASE` | yes | public bucket for mp3s |
| `SHOTSTACK_API_KEY`, `SHOTSTACK_ENV` | yes | `v1` for production (no watermark), `stage` for sandbox |
| `DATABASE_URL` | yes on Vercel | injected by the Marketplace Postgres integration. Unset locally → SQLite at `./pdf2video.db` |
| `RUN_PASSCODE` | recommended | if set, creating a job requires header `X-Passcode` |
| `SAMPLE_VIDEOS` | optional | JSON list of `{"title","url"}` shown on the landing page |

## How to continue
1. `git checkout vercel-migration`, create a venv, `pip install -r requirements.txt`, `cp .env.example .env`, fill keys.
2. `uvicorn app.main:app --reload`, open http://localhost:8000.
3. `pytest` before every commit.
4. Deploy: `vercel login` once, then `vercel link` (creates the project), `vercel env add …` for each variable, `vercel deploy`, then `vercel deploy --prod`.
5. Provision the database from the Vercel dashboard → Storage → Marketplace → Postgres (free tier). It injects `DATABASE_URL`.

## Open risks
- Opus 5 planning on a long paper could approach the 300 s Hobby limit. Mitigation: `effort: medium`, or switch planning to Sonnet 5.
- Kodisc credits per render-second are not documented publicly; measure on the first real run and record it here.
- Shotstack free production minutes are limited; each paper is ~5 minutes of output video.
- ElevenLabs free tier covers roughly two papers per month.

## Session log
- **2026-09-23, session 1**: full codebase review; verified fix branch; chose Vercel + step-driven design; wrote docs. Next: step 2 (`JobStore`).
