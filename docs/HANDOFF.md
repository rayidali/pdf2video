# Handoff — pdf2video on Vercel

_Last updated: 2026-09-23 (end of session 1)._ Update this file whenever a step in `MIGRATION_PLAN.md` changes state.

## Where things stand
| Item | State |
|---|---|
| Code | branch `vercel-migration`, PR #45 → `main` (https://github.com/rayidali/pdf2video/pull/45). Not merged yet. |
| Vercel project | `rayidalis-projects/pdf2video`, linked to the GitHub repo. Framework preset: Services (FastAPI). |
| Production URL | **https://pdf2video-wine.vercel.app** (also `pdf2video-rayidalis-projects.vercel.app`). `pdf2video.vercel.app` was taken. |
| Production state | **Public and healthy.** Deployment Protection is Standard (previews private, production open). |
| API keys | Set in Vercel for Production + Preview. `RUN_PASSCODE` is set (ask the owner). |
| Database | **Neon Postgres provisioned** (`pdf2video-db`, plan `free_v3`) via the Marketplace. `DATABASE_URL` is injected into all environments and verified from Vercel and locally. |
| Tests | `pytest`: 14 passing. CI workflow in `.github/workflows/ci.yml`. |
| **End-to-end** | **Verified on production 2026-09-23**: job `10ebc935`, *Attention Is All You Need*, 11/11 slides rendered on tier 1, 11/11 narrated, final 3:56 mp4 in R2. 17 minutes wall clock. The landing-page gallery shows it (`SAMPLE_VIDEOS` points at the R2 key). |

## Go-live checklist
All done on 2026-09-23: production public (Standard Protection), Neon Postgres (`free_v3`), API keys, passcode, first real run, gallery. What remains:
- **Merge PR #45** so `main` matches production (pushes to `main` auto-deploy).
- Put https://pdf2video-wine.vercel.app on the resume. Share the passcode only with people who should be able to spend credits; everyone else can watch the gallery.
- Optional: a custom domain (you own rayidali.com) via Settings → Domains.

### For reference: adding the API keys (each command prompts for the value; pick `Production` when asked, and also `Preview` if you want branch deploys to work):
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
4. **Redeploy so new env vars apply:** `vercel deploy --prod`. Env changes never reach an existing deployment.

## Measured cost per paper (11 slides, run of 2026-09-23)
| Vendor | Used | Allowance | Papers per month on the allowance |
|---|---|---|---|
| Kodisc | 562 credits (~51 per render) | 1,000 free/mo + 20,000 paid on the account | ~2 free, ~35 more on the paid balance |
| ElevenLabs | 1,555 characters (turbo model bills at 50%) | 300,000/mo (Creator) | ~190 |
| Shotstack (v1) | 1 render, 3:56 of video | 20 min/mo free production + 10 trial credits | ~5 |
| Anthropic | 1 plan call + 11 code calls on Opus 5 | pay as you go | roughly $1 per paper |
| Mistral | 0 (pypdf extracted the text) | not needed for born-digital PDFs | — |
| Vercel, Neon, R2 | — | free tiers | unlimited for this traffic |
Shotstack is the tightest free budget. Switch `SHOTSTACK_ENV` to `stage` for unlimited watermarked renders if it runs out.

## Decisions made
| Decision | Why |
|---|---|
| Stay on Python/FastAPI, host on Vercel Hobby | User wants Vercel and free hosting. Vercel runs FastAPI natively on Fluid Compute. |
| Browser drives the pipeline, one short request per step | No background tasks survive on serverless. Each step is bounded and independently retryable. Job is resumable by id if the tab closes. |
| One JSON document per job in Postgres | Simplest persistence that survives restarts; free tier on the Marketplace. SQLite locally with the same interface. |
| Neon over Supabase | Both are Postgres and both work with `DATABASE_URL`/`POSTGRES_URL`. Supabase's free tier pauses a project after 7 idle days, which would break a resume demo; Neon's free tier scales to zero and wakes on the next query. |
| Drop ffmpeg entirely | The trim existed only to cut a fade-to-black tail. In v2 we author the Manim code, so scenes end on the final frame and Shotstack holds that frame under the voiceover. Verified on the real run: held frames are the composed slides. |
| pypdf first, Mistral OCR only as fallback | The owner's Mistral key has zero OCR quota (`x-ratelimit-limit-req-minute: 0`). pypdf extracts born-digital PDFs for free; OCR is only attempted when a PDF looks scanned. MinerU's hosted API is the candidate free fallback. |
| Presigned R2 URLs, private bucket | The bucket's r2.dev public URL returns 401. Presigned GET URLs (7-day max) are minted on every read, so nothing depends on public access. |
| Copy the final mp4 into R2 | Shotstack deletes renders after ~24 h. The poll handler downloads the finished file and stores it as `{job}_final.mp4`. |
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
- Planning took 55 s on a 15-page paper. A very long paper could approach the 300 s Hobby limit; switch `PLAN_MODEL` to `claude-sonnet-5` if it ever times out.
- The final-video copy into R2 happens inside one poll request. A very long video (>100 MB) could push that request toward the limit; if so, move the copy behind a separate endpoint.
- Presigned URLs expire after 7 days but are re-minted on every page load, so links in the UI never go stale. A link copied out of the UI will stop working after a week.
- Scanned PDFs currently fail unless a Mistral OCR quota exists. MinerU's hosted API is the planned free replacement.
- `.env.local` on the dev machine holds the production secrets (pulled for local testing). It is gitignored; delete it if the machine is shared.

## Ideas for the next session (impact order)
1. Render two slides concurrently from the browser (halves the 12-minute render phase).
2. Kodisc `webhookUrl` + Shotstack callback instead of polling.
3. Prompt caching on the two system prompts once they exceed the model's minimum cacheable size.
4. MinerU hosted API as the scanned-PDF fallback.
5. README demo GIF and a short architecture diagram image for the resume link.

## Session log
- **2026-09-23, session 1**: full codebase review; verified fix branch; chose Vercel + step-driven design; rewrote services, router, store, frontend, tests; deployed preview and production; opened PR #45. Owner set protection, accepted Neon terms, added keys. Fixed Mistral (no OCR quota → pypdf) and R2 (no public access → presigned). First full run succeeded: job `10ebc935`, 17 minutes, 11/11 slides. Gallery set. Not done: automated browser check of the UI (needs the owner to pick a Chrome instance).
