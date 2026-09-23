# Architecture and migration plan

Status: **complete** as of 2026-09-23. Kept as the architecture reference. Day-to-day status lives in `HANDOFF.md`.

## Why the old app could not be deployed as-is
1. Job state lived in Python dicts. Vercel instances scale to zero and are shared, so state vanished.
2. Uploads and outputs were written to the repo directory. Only `/tmp` is writable on Vercel and it is ephemeral.
3. The whole pipeline ran as one FastAPI background task for 20 to 50 minutes. Vercel Hobby functions stop at 300 s.
4. Final assembly shelled out to ffmpeg to trim a fade-to-black tail off each clip. ffmpeg is not in the Python runtime.
5. Sync Anthropic and boto3 calls blocked the event loop, which froze the progress polling.
6. It targeted Kodisc's removed v1 API (prompt-to-video). v2 only renders Manim code you supply.

## Architecture
```
browser (static/app.js): drives the steps in order, resumable by ?job=<id>
   │ one short HTTPS call per step, X-Passcode header on every POST
   ▼
FastAPI on Vercel Fluid Compute (app/main.py, one function, ≤300 s per call)
   │ reads/writes one JSON row per job
   ▼
Neon Postgres (free tier)          Cloudflare R2 (private; presigned URLs on read)

per step:
   upload      pypdf extracts text (Mistral OCR only if the PDF looks scanned)   sync, seconds
   plan        Claude Opus 5 → PresentationPlan via structured output           sync, ~1 min
   render n    Claude Opus 5 writes a Manim scene → Kodisc v2 render submitted  sync, ~20–60 s
   poll n      one Kodisc status check; on failure bump the tier and resubmit   instant
   voice n     ElevenLabs mp3 → R2 (real duration via mutagen)                  sync, ~2 s
   assemble    Shotstack timeline (clip length = narration; last frame held)    sync, seconds
   poll        one Shotstack status check; on done copy the mp4 into R2         instant / ~10 s
```
Tiers per slide: 1 = Opus from the plan, 2 = Opus given the renderer's error, 3 = deterministic text slide (no LLM). Static AST validation runs before every submit and escalates to the next tier on failure.

## HTTP API
| Method | Path | Does |
|---|---|---|
| GET | `/api/config` | passcode required?, sample gallery, which services are configured |
| GET | `/api/jobs` | recent jobs (summaries) |
| POST | `/api/jobs` | multipart PDF → extract text → job created |
| GET | `/api/jobs/{id}` | full job document with fresh presigned URLs |
| GET | `/api/jobs/{id}/markdown` | extracted text |
| POST | `/api/jobs/{id}/plan` | Claude → plan (cached unless `?force=true`) |
| POST | `/api/jobs/{id}/slides/{n}/render` | write Manim for the current tier, submit to Kodisc |
| GET | `/api/jobs/{id}/slides/{n}` | one Kodisc status check; escalates tier on failure |
| GET | `/api/jobs/{id}/slides/{n}/code` | the Manim code that was submitted |
| POST | `/api/jobs/{id}/voice/{n}` | ElevenLabs → R2 |
| POST | `/api/jobs/{id}/assemble` | submit the Shotstack edit |
| GET | `/api/jobs/{id}/assemble` | one Shotstack status check; copies the final mp4 into R2 when done |
Every POST requires `X-Passcode` when `RUN_PASSCODE` is set. Job ids are 8 hex chars; anything else is a 404.

## Migration checklist
- [x] 0. Understand both branches; verify the Kodisc v2 fix boots and matches Kodisc's public docs
- [x] 1. Branch off the fix; write the docs
- [x] 2. `JobStore` (SQLite + Postgres), `Job` schema, config cleanup (no repo-dir writes)
- [x] 3. Services: async Anthropic + Opus 5 + structured outputs; Kodisc submit/check; ElevenLabs real duration; no ffmpeg; scenes hold the last frame
- [x] 4. Step-based router; delete the Generative Manim path, prompt sanitizer, dev fixtures
- [x] 5. Frontend: step driver with resume, passcode gate, sample gallery
- [x] 6. Tests (pytest, faked vendors) + GitHub Actions
- [x] 7. `vercel.json` services block, project linked, Deployment Protection → Standard, Neon Postgres, env vars
- [x] 8. End-to-end run with real keys (job `10ebc935`, 17 min, 11/11 slides). Along the way: pypdf instead of Mistral, presigned R2 instead of a public bucket, final mp4 copied into R2
- [x] 9. README rewritten, gallery live, PR #45 merged to `main`
- [ ] Later (see HANDOFF "Next ideas"): concurrent renders, webhooks, MinerU fallback, prompt caching, demo GIF, self-hosted Manim

## Free-tier ledger (measured 2026-09-23)
| Service | Allowance | Measured per paper |
|---|---|---|
| Vercel Hobby | free, non-commercial; 300 s per function | ~40 short requests |
| Neon Postgres | free tier | one small row per job |
| Cloudflare R2 | 10 GB storage, 10 M reads/mo | ~20 MB (11 mp3 + final mp4) |
| Kodisc | 1,000 credits/mo, no card | 562 credits (~51 per 720p render) |
| ElevenLabs | owner is on Creator (300k chars/mo) | 1,555 chars |
| Shotstack | 20 production min/mo free; sandbox unlimited but watermarked | ~4 min |
| Anthropic | pay as you go | $1.23 on Opus 5, $0.49 on Sonnet 5 |
| Mistral OCR | not used | pypdf extracts the text |
