# Handoff — pdf2video on Vercel

_Last updated: 2026-09-23, end of session 1. Everything below is live and verified._

## Where things stand
| Item | State |
|---|---|
| Live URL | **https://pdf2video-wine.vercel.app** (also `pdf2video-rayidalis-projects.vercel.app`; `pdf2video.vercel.app` was taken) |
| Code | `main` on GitHub. PR #45 merged 2026-09-23. Pushes to `main` auto-deploy production. The `vercel-migration` branch can be deleted. |
| Vercel project | `rayidalis-projects/pdf2video`, Hobby plan, Services framework preset (FastAPI). Deployment Protection = Standard (previews private, production public). |
| Database | Neon Postgres `pdf2video-db` (Marketplace, plan `free_v3`). `DATABASE_URL` injected into all environments. |
| API keys | All set for Production + Preview. `RUN_PASSCODE` gates every POST; only the owner knows it. |
| Gallery | `SAMPLE_VIDEOS` points at the R2 key of the verified run, so the landing page shows a finished video instantly. |
| Verified run | Job `10ebc935`, *Attention Is All You Need*: 11/11 slides rendered on tier 1, 11/11 narrated, 3:56 final mp4 in R2, 17 minutes wall clock. |
| Tests / CI | 14 pytest tests, all vendors faked. GitHub Actions green on `main`. |

## What remains for the owner
- Put https://pdf2video-wine.vercel.app on the resume. Give the passcode only to people who should be able to spend credits; everyone else watches the gallery.
- Optional: custom domain via Vercel → Settings → Domains (rayidali.com is already on the account).
- Optional: delete `.env.local` on the Mac if the machine is shared. It holds production secrets for local testing and is gitignored.
- Not done: an automated browser walkthrough of the UI. The tool needed the owner to pick one of three connected Chromes. The API and the job page were verified by direct requests instead.

## How to run, test, deploy
```
git clone https://github.com/rayidali/pdf2video && cd pdf2video
python -m venv .venv && source .venv/bin/activate && pip install -r requirements-dev.txt
cp .env.example .env                                    # fill in keys; SQLite is used when DATABASE_URL is unset
uvicorn app.main:app --reload                           # http://localhost:8000
pytest                                                  # offline, < 1 s
vercel deploy                                           # preview URL (protected)
vercel deploy --prod                                    # production
vercel env pull .env.local --environment=production     # production secrets for local scripts
```
Env changes never reach an existing deployment; redeploy after `vercel env add`.

## Environment variables
| Name | Required | Notes |
|---|---|---|
| `ANTHROPIC_API_KEY` | yes | `PLAN_MODEL` / `CODE_MODEL` default to `claude-opus-5`; set both to `claude-sonnet-5` to cut Anthropic cost to $0.49 per paper |
| `KODISC_API_KEY` | yes | v2 key from kodisc.com/developer, starts with `kdsc_live_`. `KODISC_QUALITY` default `medium` (720p30) |
| `ELEVENLABS_API_KEY` | yes | `ELEVENLABS_VOICE_ID`, `ELEVENLABS_MODEL_ID` optional |
| `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_ENDPOINT_URL`, `R2_BUCKET_NAME` | yes | bucket may stay private; presigned URLs are used. `R2_PUBLIC_URL_BASE` is unused |
| `SHOTSTACK_API_KEY`, `SHOTSTACK_ENV` | yes | `v1` = production (no watermark, 20 free min/mo), `stage` = unlimited sandbox with watermark |
| `DATABASE_URL` or `POSTGRES_URL` | on Vercel | injected by the Marketplace integration; unset locally → SQLite `./pdf2video.db` |
| `RUN_PASSCODE` | recommended | every POST must send header `X-Passcode`; the UI prompts for it |
| `SAMPLE_VIDEOS` | optional | JSON list of `{"title", "key"}` (R2 key, presigned on read) or `{"title", "url"}` |
| `MISTRAL_API_KEY` | optional | only used when a PDF looks scanned. The owner's key has zero OCR quota, so scans currently fail |
| `MAX_UPLOAD_MB` | optional | default 25 |

## Measured cost per paper (11 slides, run of 2026-09-23)
| Vendor | Used per paper | Allowance | Papers per month on the allowance |
|---|---|---|---|
| Anthropic, Opus 5 | plan 17.5k in / 3.7k out = $0.18; each slide 2.3k in / 3.3k out = $0.095 | pay as you go | **$1.23 per paper** ($0.49 on Sonnet 5) |
| Kodisc | 562 credits (~51 per 720p render) | 1,000 free/mo + 20,000 paid on the account | ~2 free, ~35 on the paid balance |
| ElevenLabs | 1,555 characters (turbo bills at 50%) | 300,000/mo (Creator) | ~190 |
| Shotstack (v1) | one render, 3:56 of video | 20 free min/mo, then $0.30/min | ~5 free |
| Mistral | 0 (pypdf extracted the text) | — | — |
| Vercel, Neon, R2 | 0 | free tiers | unlimited at this traffic |

**Bottom line:** about **$1.25 in cash per paper** while the other vendors stay inside their allowances; roughly **$3.50–4.00** if everything were paid at list price. Paper length barely matters: the 15-page paper was ~15k input tokens (about $0.08), so each extra page adds about half a cent. The eleven fixed per-slide calls are the bill. Shotstack's 20 free minutes is the tightest budget; switch to `stage` (watermarked) if it runs out.

## Decisions made
| Decision | Why |
|---|---|
| Stay on Python/FastAPI, host on Vercel Hobby | Owner wanted Vercel and free hosting. Vercel runs FastAPI natively on Fluid Compute. |
| Browser drives the pipeline, one short request per step | No background task survives on serverless. Each step is bounded and independently retryable; any job resumes by id. |
| One JSON document per job in Postgres | Simplest persistence that survives restarts. SQLite locally with the same interface. |
| Neon over Supabase | Both are Postgres. Supabase's free tier pauses after 7 idle days, which would break a resume demo; Neon scales to zero and wakes on the next query. |
| pypdf first, Mistral OCR only as fallback | The owner's Mistral key reports `x-ratelimit-limit-req-minute: 0` for OCR. pypdf extracts born-digital PDFs for free. |
| Drop ffmpeg entirely | The old trim only removed a fade-to-black tail. We author the Manim now, so scenes hold their final frame and Shotstack holds it under the narration. Verified on the real run. |
| Private R2 + presigned URLs | The bucket's r2.dev public URL returns 401. Presigned GET URLs (7-day max) are minted on every read, so nothing depends on public access. |
| Copy the final mp4 into R2 | Shotstack deletes renders after ~24 h. The poll handler stores `{job}_final.mp4` in R2. |
| Opus 5 with structured outputs | Removes the JSON repair hack; the plan is guaranteed to match the Pydantic schema. |
| Three render tiers per slide | Opus from the plan → Opus given the renderer's error → deterministic text slide. A video always comes out. All 11 slides used tier 1 on the verified run. |
| Polling, not webhooks | Works without callback signature docs. Webhooks are a later optimization. |
| `services` block in `vercel.json` | Vercel CLI 59 detects FastAPI as a service and rejects a top-level `functions` key. Hobby's 300 s default is already the maximum. |

## Open risks
- Planning took 55 s on a 15-page paper. A very long paper could approach the 300 s Hobby limit; switch `PLAN_MODEL` to `claude-sonnet-5` if it ever times out.
- The final-video copy into R2 runs inside one poll request. A >100 MB output could push that request toward the limit.
- Presigned URLs expire after 7 days but are re-minted on every page load. A link copied out of the UI dies after a week.
- Scanned PDFs fail unless a Mistral OCR quota exists. MinerU's hosted API is the planned free replacement.
- Kodisc's v2 API is a small vendor's contract; it worked today, but it is the dependency that broke the project once before. Self-hosting Manim would remove it.

## Next ideas, in impact order
0. Cheaper: set `CODE_MODEL` and `PLAN_MODEL` to `claude-sonnet-5` ($0.49 per paper). Check slide quality on one paper first.
1. Render two slides concurrently from the browser (halves the 12-minute render phase).
2. Kodisc `webhookUrl` and Shotstack callback instead of polling.
3. MinerU's hosted API as the scanned-PDF fallback (async submit/poll, free quota).
4. Prompt caching on the two system prompts once they exceed the model's minimum cacheable size.
5. README demo GIF and an architecture diagram image for the resume link.
6. Self-hosted Manim renderer to drop the Kodisc dependency (needs an always-on box; not free).

## Session log
- **2026-09-23, session 1**: reviewed both branches; verified the Kodisc v2 fix; chose Vercel with a step-driven design; rewrote services, router, store, frontend, tests; deployed preview and production; owner set protection, accepted Neon terms, added keys and passcode; fixed Mistral (no OCR quota → pypdf) and R2 (no public access → presigned); first full run succeeded (job `10ebc935`, 17 min, 11/11 slides); gallery set; PR #45 merged; costs measured; failed test job removed from the database. Session closed with everything live.
