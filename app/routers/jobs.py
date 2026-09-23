"""Job endpoints.

Every handler is one bounded unit of work (well under Vercel's 300 s cap) and persists
its result before returning. The browser drives the sequence and can resume any job by
id, so a closed tab or a redeploy never loses work.
"""
import json
import logging
import re
import uuid
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, File, Header, HTTPException, UploadFile

from app import deps
from app.config import settings
from app.models.schemas import Job, SlideContent, SlideState
from app.services.manim_validator import validate_code
from app.services.safe_slide_template import render_safe_slide_code
from app.services.shotstack_service import SlideAsset

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["jobs"])

JOB_ID_RE = re.compile(r"^[a-f0-9]{8}$")
MAX_SUBMIT_ATTEMPTS = 5
NO_AUDIO_HOLD_SECONDS = 12.0
KODISC_COLORS = {"primary": "#58C4DD", "secondary": "#FC6255", "background": "#000000", "text": "#FFFFFF"}


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def require_passcode(x_passcode: Optional[str] = Header(default=None)) -> None:
    if settings.RUN_PASSCODE and x_passcode != settings.RUN_PASSCODE:
        raise HTTPException(status_code=401, detail="Passcode required")


async def load_job(job_id: str) -> Job:
    if not JOB_ID_RE.match(job_id):
        raise HTTPException(status_code=404, detail="Job not found")
    job = await deps.store.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


def slide_of(job: Job, n: int) -> tuple[SlideState, SlideContent]:
    state = job.slide(n)
    content = next((s for s in job.plan.slides if s.slide_number == n), None) if job.plan else None
    if state is None or content is None:
        raise HTTPException(status_code=404, detail=f"Slide {n} not found. Create the plan first.")
    return state, content


def slide_public(state: SlideState) -> dict:
    d = state.model_dump()
    d["has_code"] = bool(d.pop("code", None))
    return d


def _safe_code(content: SlideContent, class_name: str) -> str:
    return render_safe_slide_code(
        title=content.fallback_title or content.title,
        bullets=content.fallback_points or content.key_points or ["Key idea", "How it works", "Why it matters"],
        class_name=class_name,
        colors=KODISC_COLORS,
        duration_seconds=float(content.duration_seconds or 8),
    )


async def _code_for_slide(job: Job, state: SlideState, content: SlideContent, class_name: str) -> tuple[str, str]:
    """Return (code, tier_used) for the slide's current tier, escalating to the safe
    template when Claude's output fails static validation."""
    plan = job.plan
    try:
        if state.tier == 1:
            generated = await deps.manim.generate_slide_code(content, plan.paper_title, plan.paper_summary)
            code = generated.manim_code
            problems = validate_code(code, class_name)
            if problems:
                logger.warning(f"[{job.id}] {class_name} tier1 static problems: {problems}")
                code = await deps.manim.fix_code(code, problems, class_name)
                problems = validate_code(code, class_name)
            if not problems:
                return code, "opus_primary"
            logger.warning(f"[{job.id}] {class_name} still invalid after fix; using safe template")
        elif state.tier == 2 and state.code:
            errors = [f"Runtime error reported by the Manim renderer: {state.error or 'unknown'}"]
            code = await deps.manim.fix_code(state.code, errors, class_name)
            if not validate_code(code, class_name):
                return code, "opus_retry"
            logger.warning(f"[{job.id}] {class_name} tier2 fix invalid; using safe template")
    except Exception as e:  # LLM outage, bad key, timeout: never block the slide on it
        logger.error(f"[{job.id}] {class_name} code generation error at tier {state.tier}: {e}")
    state.tier = 3
    return _safe_code(content, class_name), "safe_template"


def _parse_samples() -> list[dict]:
    try:
        samples = json.loads(settings.SAMPLE_VIDEOS or "[]")
        return [s for s in samples if isinstance(s, dict) and s.get("url")]
    except json.JSONDecodeError:
        logger.warning("SAMPLE_VIDEOS is not valid JSON")
        return []


# ---------------------------------------------------------------------------
# config + listing
# ---------------------------------------------------------------------------

@router.get("/config")
async def get_config():
    return {
        "passcode_required": bool(settings.RUN_PASSCODE),
        "samples": _parse_samples(),
        "services": deps.service_status(),
        "max_upload_mb": settings.MAX_UPLOAD_MB,
    }


@router.get("/jobs")
async def list_jobs():
    return {"jobs": await deps.store.list()}


@router.get("/jobs/{job_id}")
async def get_job(job_id: str):
    job = await load_job(job_id)
    return job.public()


@router.get("/jobs/{job_id}/markdown")
async def get_markdown(job_id: str):
    job = await load_job(job_id)
    if not job.markdown:
        raise HTTPException(status_code=404, detail="No markdown yet")
    return {"job_id": job.id, "markdown": job.markdown}


@router.get("/jobs/{job_id}/slides/{n}/code")
async def get_slide_code(job_id: str, n: int):
    job = await load_job(job_id)
    state, _ = slide_of(job, n)
    if not state.code:
        raise HTTPException(status_code=404, detail="No code generated yet")
    return {"job_id": job.id, "slide_number": n, "tier_used": state.tier_used, "code": state.code}


# ---------------------------------------------------------------------------
# step 1: upload + OCR
# ---------------------------------------------------------------------------

@router.post("/jobs", dependencies=[Depends(require_passcode)])
async def create_job(file: UploadFile = File(...)):
    name = Path(file.filename or "paper.pdf").name
    if not name.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are accepted")
    data = await file.read()
    if len(data) > settings.MAX_UPLOAD_MB * 1024 * 1024:
        raise HTTPException(status_code=413, detail=f"PDF larger than {settings.MAX_UPLOAD_MB} MB")
    if not data.startswith(b"%PDF"):
        raise HTTPException(status_code=400, detail="File does not look like a PDF")

    safe_name = re.sub(r"[^A-Za-z0-9._-]+", "_", name)[:80] or "paper.pdf"
    job = Job(id=uuid.uuid4().hex[:8], filename=safe_name)
    logger.info(f"[{job.id}] upload {safe_name} ({len(data)} bytes)")

    try:
        markdown = await deps.ocr.pdf_to_markdown(data, safe_name)
    except Exception as e:
        job.step, job.error = "failed", f"OCR failed: {e}"
        await deps.store.create(job)
        raise HTTPException(status_code=502, detail=job.error)

    if not markdown.strip():
        job.step, job.error = "failed", "OCR returned no text"
        await deps.store.create(job)
        raise HTTPException(status_code=422, detail=job.error)

    job.markdown, job.step = markdown, "ocr_complete"
    await deps.store.create(job)
    return {"job": job.public(), "markdown_preview": markdown[:600]}


# ---------------------------------------------------------------------------
# step 2: plan
# ---------------------------------------------------------------------------

@router.post("/jobs/{job_id}/plan", dependencies=[Depends(require_passcode)])
async def create_plan(job_id: str, force: bool = False):
    job = await load_job(job_id)
    if job.plan and not force:
        return {"job": job.public(), "cached": True}
    if not job.markdown:
        raise HTTPException(status_code=400, detail="No markdown; upload a PDF first")
    try:
        plan = await deps.planner.create_presentation_plan(job.markdown)
    except Exception as e:
        job.error = f"Planning failed: {e}"
        await deps.store.save(job)
        raise HTTPException(status_code=502, detail=job.error)
    job.apply_plan(plan)
    job.error, job.fatal = None, False
    await deps.store.save(job)
    return {"job": job.public(), "cached": False}


# ---------------------------------------------------------------------------
# step 3: render slides (submit, then poll)
# ---------------------------------------------------------------------------

@router.post("/jobs/{job_id}/slides/{n}/render", dependencies=[Depends(require_passcode)])
async def render_slide(job_id: str, n: int, force: bool = False):
    job = await load_job(job_id)
    state, content = slide_of(job, n)
    if state.status == "done" and not force:
        return {"slide": slide_public(state), "fatal": False, "cached": True}
    if state.status in ("submitted", "rendering") and state.kodisc_job_id and not force:
        return {"slide": slide_public(state), "fatal": False, "cached": True}
    if state.attempts >= MAX_SUBMIT_ATTEMPTS and not force:
        state.status = "failed"
        await deps.store.save(job)
        return {"slide": slide_public(state), "fatal": False}

    class_name = f"Slide{n:03d}"
    code, tier_used = await _code_for_slide(job, state, content, class_name)
    state.code, state.tier_used = code, tier_used
    state.attempts += 1

    result = await deps.kodisc.submit(code, class_name, quality=settings.KODISC_QUALITY)
    if result.success:
        state.kodisc_job_id, state.status, state.error = result.job_id, "submitted", None
        job.step, job.fatal, job.error = "rendering", False, None
    else:
        state.error = result.error
        if result.is_fatal:
            state.status = "failed"
            job.fatal, job.error = True, result.error
        else:
            state.status = "retry" if state.attempts < MAX_SUBMIT_ATTEMPTS else "failed"
    await deps.store.save(job)
    return {"slide": slide_public(state), "fatal": job.fatal}


@router.get("/jobs/{job_id}/slides/{n}")
async def poll_slide(job_id: str, n: int):
    job = await load_job(job_id)
    state, _ = slide_of(job, n)
    if state.status in ("submitted", "rendering") and state.kodisc_job_id:
        result = await deps.kodisc.check(state.kodisc_job_id)
        if result.is_done:
            state.status, state.error = "done", None
            state.video_url, state.thumbnail_url = result.video_url, result.thumbnail_url
        elif result.is_failed:
            state.error = result.error
            if result.is_fatal:
                state.status = "failed"
                job.fatal, job.error = True, result.error
            elif state.tier < 3:
                state.tier += 1
                state.status = "retry"
            else:
                state.status = "failed"
        else:
            state.status = "rendering"
        await deps.store.save(job)
    return {"slide": slide_public(state), "fatal": job.fatal}


# ---------------------------------------------------------------------------
# step 4: voiceovers
# ---------------------------------------------------------------------------

@router.post("/jobs/{job_id}/voice/{n}", dependencies=[Depends(require_passcode)])
async def voice_slide(job_id: str, n: int, force: bool = False):
    job = await load_job(job_id)
    _, content = slide_of(job, n)
    audio = job.audio_for(n)
    if audio.status == "done" and not force:
        return {"audio": audio.model_dump(), "cached": True}

    script = (content.voiceover_script or "").strip()
    if not script:
        audio.status, audio.error = "skipped", "No voiceover script"
        await deps.store.save(job)
        return {"audio": audio.model_dump(), "cached": False}

    tts = await deps.tts.generate_voiceover(script)
    if not tts.success:
        audio.status, audio.error = "failed", tts.error
        await deps.store.save(job)
        return {"audio": audio.model_dump(), "cached": False}

    upload = await deps.r2.upload_async(tts.audio_data, f"{job.id}_s{n:03d}.mp3", "audio/mpeg")
    if not upload.success:
        audio.status, audio.error = "failed", f"Upload failed: {upload.error}"
        await deps.store.save(job)
        return {"audio": audio.model_dump(), "cached": False}

    audio.status, audio.error = "done", None
    audio.audio_url, audio.duration_seconds = upload.public_url, tts.duration_seconds
    job.step = "voicing"
    await deps.store.save(job)
    return {"audio": audio.model_dump(), "cached": False}


# ---------------------------------------------------------------------------
# step 5: final assembly (submit, then poll)
# ---------------------------------------------------------------------------

@router.post("/jobs/{job_id}/assemble", dependencies=[Depends(require_passcode)])
async def assemble(job_id: str, force: bool = False):
    job = await load_job(job_id)
    final = job.final
    if final.status == "done" and not force:
        return {"final": final.model_dump(), "step": job.step, "cached": True}
    if final.status in ("submitted", "rendering") and final.render_id and not force:
        return {"final": final.model_dump(), "step": job.step, "cached": True}

    assets: list[SlideAsset] = []
    for key in sorted(job.slides, key=int):
        s = job.slides[key]
        if s.status != "done" or not s.video_url:
            continue
        a = job.audio.get(key)
        has_audio = bool(a and a.status == "done" and a.audio_url and a.duration_seconds)
        assets.append(SlideAsset(
            slide_number=s.slide_number,
            video_url=s.video_url,
            audio_url=a.audio_url if has_audio else None,
            audio_duration=a.duration_seconds if has_audio else None,
            fallback_duration=NO_AUDIO_HOLD_SECONDS,
            title=s.title,
        ))
    if not assets:
        raise HTTPException(status_code=400, detail="No rendered slides to assemble")

    result = await deps.shotstack.submit_render(assets)
    if not result.success:
        final.status, final.error = "failed", result.error
        await deps.store.save(job)
        return {"final": final.model_dump(), "step": job.step, "cached": False}

    final.render_id, final.status, final.error = result.render_id, "submitted", None
    job.step = "assembling"
    await deps.store.save(job)
    return {"final": final.model_dump(), "step": job.step, "cached": False}


@router.get("/jobs/{job_id}/assemble")
async def poll_assemble(job_id: str):
    job = await load_job(job_id)
    final = job.final
    if final.status in ("submitted", "rendering") and final.render_id:
        result = await deps.shotstack.check_render_status(final.render_id)
        if result.status == "done":
            final.status, final.video_url, final.error = "done", result.video_url, None
            job.step = "complete"
        elif result.status == "failed" or not result.success:
            final.status, final.error = "failed", result.error
        else:
            final.status = "rendering"
        await deps.store.save(job)
    return {"final": final.model_dump(), "step": job.step}
