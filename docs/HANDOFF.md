# Handoff — pdf2video on Vercel

_Last updated: 2026-09-23 by Claude (session 1)._ Update this file whenever a step in `MIGRATION_PLAN.md` changes state.

## Where things stand
| Item | State |
|---|---|
| Code | branch `vercel-migration`, PR #45 → `main` (https://github.com/rayidali/pdf2video/pull/45). Not merged yet. |
| Vercel project | `rayidalis-projects/pdf2video`, linked to the GitHub repo. Framework preset: Services (FastAPI). |
| Production URL | **https://pdf2video-wine.vercel.app** (also `pdf2video-rayidalis-projects.vercel.app`). `pdf2video.vercel.app` was taken. |
| Production state | Deployed and healthy, but **Deployment Protection is on for production**, so visitors get a Vercel login redirect. Fix below. |
| API keys | **None set yet.** The app boots and shows "Not configured" until they are added. |
| Database | Not provisioned yet. App falls back to SQLite in `/tmp` (works, but forgets jobs on cold start). |
| Tests | `pytest`: 11 passing. CI workflow in `.github/workflows/ci.yml`. |

## Do these four things to go live (in order)
1. **Make production public.** Dashboard → https://vercel.com/rayidalis-projects/pdf2video/settings/deployment-protection → Vercel Authentication → choose *Standard Protection* (previews stay private, production is public). Verify with `curl https://pdf2video-wine.vercel.app/health` → `{"status":"healthy"}`.
2. **Accept the Neon Marketplace terms once** in the browser: https://vercel.com/rayidalis-projects/~/integrations/accept-terms/neon?source=cli . Then run:
   ```
   vercel integration add neon --plan free --name pdf2video-db --no-claim
   ```
   It creates a free Postgres and injects `DATABASE_URL` into the project.
3. **Add the API keys** (each command prompts for the value; pick `Production` when asked, and also `Preview` if you want branch deploys to work):
   ```
   vercel env add ANTHROPIC_API_KEY
   vercel env add MISTRAL_API_KEY
   vercel env add KODISC_API_KEY        # NEW v2 key from https://kodisc.com/developer, starts with kdsc_live_
   vercel env add ELEVENLABS_API_KEY
   vercel env add R2_ACCESS_KEY_ID
   vercel env add R2_SECRET_ACCESS_KEY
   vercel env add R2_ENDPOINT_URL       # https://<account-id>.r2.cloudflarestorage.com
   vercel env add R2_BUCKET_NAME
   vercel env add R2_PUBLIC_URL_BASE    # https://pub-....r2.dev  (bucket must be public)
   vercel env add SHOTSTACK_API_KEY
   vercel env add SHOTSTACK_ENV         # stage (free, watermark) or v1 (production)
   vercel env add RUN_PASSCODE          # any secret word; the UI asks for it before spending credits
   ```
   The old config had these R2 defaults, in case they are still yours: endpoint `https://c0ebff86d2b3187dd34b97c37df76da6.r2.cloudflarestorage.com`, bucket `slides1`, public base `https://pub-34b1f2a534c64f48ad64ff0a3bd68992.r2.dev`.
4. **Redeploy so the new env vars apply:** `vercel deploy --prod`. Then run one paper end to end and note the Kodisc credit cost per render in this file.

After that, merge PR #45 so `main` matches production (pushes to `main` auto-deploy).

## Decisions made
| Decision | Why |
|---|---|
| Stay on Python/FastAPI, host on Vercel Hobby | User wants Vercel and free hosting. Vercel runs FastAPI natively on Fluid Compute. |
| Browser drives the pipeline, one short request per step | No background tasks survive on serverless. Each step is bounded and independently retryable. Job is resumable by id if the tab closes. |
| One JSON document per job in Postgres | Simplest persistence that survives restarts; free tier on the Marketplace. SQLite locally with the same interface. |
| Neon over Supabase | Both are Postgres and both work with `DATABASE_URL`/`POSTGRES_URL`. Supabase's free tier pauses a project after 7 idle days, which would break a resume demo; Neon's free tier scales to zero and wakes on the next query. |
| Drop ffmpeg entirely | The trim existed only to cut a fade-to-black tail. In v2 we author the Manim code, so scenes end on the final frame and Shotstack holds that frame under the voiceover (documented Shotstack behaviour). |
| Claude Opus 5 with structured outputs for planning and code | Removes the hand-rolled JSON repair. Sonnet 5 is the cheaper switch if latency or cost bite. |
| Polling, not webhooks, for Kodisc and Shotstack (for now) | Works without a public callback URL and without signature docs. Webhooks are a later optimization. |
| Passcode gate + sample gallery | A resume link gets clicked by strangers. The gate stops credit drain; the gallery gives recruiters something instant to watch. |
| `vercel.json` uses the `services` block | Vercel CLI 59 auto-detects FastAPI as a service and rejects a top-level `functions` key. Hobby's 300 s default is already the maximum, so no `maxDuration` is needed. |

## Environment variables
| Name | Required | Notes |
|---|---|---|
| `ANTHROPIC_API_KEY` | yes | Planning + Manim generation. `PLAN_MODEL`/`CODE_MODEL` default to `claude-opus-5` |
| `MISTRAL_API_KEY` | yes | OCR |
| `KODISC_API_KEY` | yes | must start with `kdsc_live_` (regenerate at kodisc.com/developer; old `kodisc_` keys are dead) |
| `ELEVENLABS_API_KEY` | yes | TTS. `ELEVENLABS_VOICE_ID`, `ELEVENLABS_MODEL_ID` optional |
| `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_ENDPOINT_URL`, `R2_BUCKET_NAME`, `R2_PUBLIC_URL_BASE` | yes | public bucket for mp3s that Shotstack fetches |
| `SHOTSTACK_API_KEY`, `SHOTSTACK_ENV` | yes | `v1` for production (no watermark), `stage` for sandbox |
| `DATABASE_URL` (or `POSTGRES_URL`) | yes on Vercel | injected by the Marketplace integration. Unset locally → SQLite at `./pdf2video.db` |
| `RUN_PASSCODE` | recommended | if set, every POST requires header `X-Passcode`; the UI prompts for it |
| `SAMPLE_VIDEOS` | optional | JSON list of `{"title","url","poster"}` shown on the landing page |
| `MAX_UPLOAD_MB` | optional | default 25 |

## How to continue locally
1. `git checkout vercel-migration`, create a venv, `pip install -r requirements-dev.txt`, `cp .env.example .env`, fill keys.
2. `uvicorn app.main:app --reload`, open http://localhost:8000.
3. `pytest` before every commit. Vendors are faked in `tests/conftest.py`; add a fake when you add a vendor.
4. `vercel deploy` for a preview, `vercel deploy --prod` for production. The CLI is already logged in on this machine.

## Open risks
- Opus 5 planning on a long paper could approach the 300 s Hobby limit. Mitigation: it already runs at `effort: medium`; switch `PLAN_MODEL` to `claude-sonnet-5` if it times out.
- `psycopg` has not yet been exercised on Vercel (no `DATABASE_URL` yet). If the first Postgres call fails, check the function logs with `vercel logs`.
- Kodisc's v2 response shape was inferred from their developer page and the PR #44 author's inspection, not from a full public spec. The client tolerates `jobId`/`id` and `result.video`/`video`. Verify on the first real render.
- Kodisc credits per render-second are not documented publicly; measure on the first real run and record it here.
- Shotstack free production minutes are limited; each paper is ~5 minutes of output video. `stage` is unlimited but watermarked.
- ElevenLabs free tier covers roughly two papers per month.

## Session log
- **2026-09-23, session 1**: full codebase review; verified fix branch; chose Vercel + step-driven design; rewrote services, router, store, frontend, tests; deployed preview and production; opened PR #45. Blocked on user actions: deployment protection, Neon terms, API keys.
