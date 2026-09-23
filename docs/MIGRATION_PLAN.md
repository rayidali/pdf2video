# Vercel migration plan

Goal: the demo link on the resume always opens, the pipeline runs end to end, and hosting costs nothing.

## Why the app could not be deployed as-is
1. Job state lived in Python dicts. Vercel instances scale to zero and are shared, so state vanished.
2. Uploads and outputs were written to the repo directory. Only `/tmp` is writable on Vercel and it is ephemeral.
3. The whole pipeline ran as one FastAPI background task for 20 to 50 minutes. Vercel Hobby functions stop at 300 s.
4. Final assembly shelled out to ffmpeg to trim a fade-to-black tail off each clip. ffmpeg is not in the Python runtime.
5. Sync Anthropic and boto3 calls blocked the event loop, which froze the progress polling.

## Target architecture
```
browser (static/app.js, drives steps, resumable by job id)
   │ one short HTTPS call per step
   ▼
FastAPI on Vercel Fluid Compute (app/main.py, ≤300 s per call)
   │ reads/writes one JSON row per job
   ▼
Postgres (Vercel Marketplace, free tier)      Cloudflare R2 (audio files, public URLs)

vendors, all submit-then-poll or synchronous-and-short:
   Mistral OCR  → markdown        (sync, ~10–60 s)
   Claude Opus 5 → plan JSON      (structured output, sync)
   Claude Opus 5 → Manim code     (sync, per slide)
   Kodisc v2     → mp4 per slide  (submit, then one status check per poll)
   ElevenLabs    → mp3 per slide  (sync, then upload to R2)
   Shotstack     → final mp4      (submit, then one status check per poll)
```

## HTTP API (new)
| Method | Path | Does | Bound |
|---|---|---|---|
| POST | `/api/jobs` | multipart PDF → create job, run OCR, store markdown | ~60 s |
| GET | `/api/jobs` | list jobs | instant |
| GET | `/api/jobs/{id}` | full job document | instant |
| POST | `/api/jobs/{id}/plan` | Claude → `PresentationPlan` via structured output | ~60–180 s |
| POST | `/api/jobs/{id}/slides/{n}/render` | Claude writes Manim for the current tier, submits to Kodisc | ~30–90 s |
| GET | `/api/jobs/{id}/slides/{n}` | one Kodisc status check; on failure bumps tier so the client can resubmit | instant |
| POST | `/api/jobs/{id}/voice/{n}` | ElevenLabs → mp3 → R2, real duration via mutagen | ~10–30 s |
| POST | `/api/jobs/{id}/assemble` | build Shotstack timeline, submit render | ~5 s |
| GET | `/api/jobs/{id}/assemble` | one Shotstack status check; stores final URL | instant |

Tiers per slide: 1 = Opus from the visual description, 2 = Opus given the Kodisc error, 3 = deterministic text slide (no LLM).

## Steps
- [x] 0. Understand both branches, verify the v2 fix boots and matches Kodisc's public docs
- [x] 1. Branch `vercel-migration` off the fix branch; write these docs
- [x] 2. `JobStore` (SQLite + Postgres), `Job` schema, config cleanup (no repo-dir writes)
- [x] 3. Services: async Anthropic + Opus 5 + structured outputs; Kodisc submit/check split; ElevenLabs real duration; drop ffmpeg; Manim scenes end on last frame
- [x] 4. New router with the API above; delete Generative Manim path, sanitizer, dev fixtures
- [x] 5. Frontend: step driver with resume, passcode gate, sample gallery
- [x] 6. Tests (pytest, mocked vendors) + GitHub Actions
- [x] 7a. `vercel.json` (services block), project linked, preview + production deploys green
- [x] 7b. Deployment Protection → Standard; Neon Postgres provisioned and verified on Vercel
- [ ] 7c. API keys via `vercel env add` + redeploy (see HANDOFF)
- [ ] 8. End-to-end run with real keys; fix what breaks
- [ ] 9. README rewrite, merge to `main`, put the URL on the resume
- [ ] later: Kodisc/Shotstack webhooks instead of polling; render 2 slides concurrently; prompt caching

## Free-tier ledger (checked 2026-09-23)
| Service | Free allowance | Notes |
|---|---|---|
| Vercel Hobby | free, non-commercial | 300 s max per function, 100 GB bandwidth |
| Postgres (Marketplace) | free tier | Neon or similar; one small table |
| Cloudflare R2 | 10 GB storage, 10 M reads/mo | already integrated |
| Kodisc | 1,000 credits/mo, no card | billed per render-second; see HANDOFF for measured cost |
| ElevenLabs | 10k chars/mo on free plan | ~4–5k chars per paper → ~2 runs/mo free |
| Shotstack | 20 min video/mo free; sandbox unlimited but watermarked | production env (`v1`) needed for no watermark |
| Mistral OCR | pay per page, cents per paper | free experiment tier exists with rate limits |
| Anthropic | paid | ~$1 per paper on Opus 5, ~$0.45 on Sonnet 5 |
