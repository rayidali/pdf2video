"""
Kodisc API Service (v2)

Public API: https://kodisc.com/api/v2
- POST /render          enqueue a render job (returns jobId)
- GET  /render/{jobId}  poll a job status
- GET  /me              inspect key + credit balance

Auth: Authorization: Bearer kdsc_live_<48 hex chars>
Body: application/json

The new public API only RENDERS Manim code that the caller provides.
It does NOT generate code from prompts — the prompt-to-code path is an
internal Kodisc surface and not part of the public contract.
"""

import asyncio
import httpx
import logging
import time
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)

KODISC_API_URL = "https://kodisc.com/api/v2"
ENQUEUE_TIMEOUT = 30
POLL_TIMEOUT = 30
POLL_INTERVAL_START = 2.0
POLL_INTERVAL_MAX = 5.0
TOTAL_RENDER_BUDGET_SECONDS = 240


@dataclass
class KodiscResult:
    """Result from a Kodisc render request."""
    success: bool
    video_url: Optional[str] = None
    thumbnail_url: Optional[str] = None
    captions_url: Optional[str] = None
    error: Optional[str] = None
    status_code: Optional[int] = None
    job_id: Optional[str] = None
    duration_ms: Optional[int] = None
    credits_cost: Optional[int] = None

    @property
    def is_auth_error(self) -> bool:
        return self.status_code in (401, 403)

    @property
    def is_credits_error(self) -> bool:
        return self.status_code == 402


class KodiscService:
    """Client for the Kodisc v2 public API."""

    def __init__(self, api_key: str, timeout: int = ENQUEUE_TIMEOUT):
        self.api_key = api_key or ""
        self.timeout = timeout

        if self.api_key and not self.api_key.startswith("kdsc_live_"):
            logger.warning(
                "Kodisc API key does not start with 'kdsc_live_'. "
                "If you regenerated under v2, the prefix should be kdsc_live_."
            )

    def is_configured(self) -> bool:
        return bool(self.api_key and self.api_key.startswith("kdsc_live_"))

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    async def render(
        self,
        code: str,
        class_name: str,
        quality: str = "medium",
        aspect_ratio: str = "16:9",
        fps: Optional[int] = None,
        webhook_url: Optional[str] = None,
        metadata: Optional[dict] = None,
    ) -> KodiscResult:
        """Enqueue a Manim render and poll until completion."""
        if not self.is_configured():
            return KodiscResult(
                success=False,
                error="KODISC_API_KEY not configured (must start with kdsc_live_)",
            )

        body: dict = {
            "code": code,
            "className": class_name,
            "quality": quality,
            "aspectRatio": aspect_ratio,
        }
        if fps is not None:
            body["fps"] = fps
        if webhook_url:
            body["webhookUrl"] = webhook_url
        if metadata:
            body["metadata"] = metadata

        logger.info(
            f"[Kodisc] enqueue render class={class_name} quality={quality} "
            f"aspect={aspect_ratio} code_len={len(code)}"
        )

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                enqueue = await client.post(
                    f"{KODISC_API_URL}/render",
                    json=body,
                    headers=self._headers(),
                )

                if enqueue.status_code not in (200, 202):
                    raw = enqueue.text[:500]
                    logger.error(f"[Kodisc] enqueue HTTP {enqueue.status_code}: {raw}")
                    err = self._format_error(enqueue.status_code, raw)
                    return KodiscResult(
                        success=False,
                        status_code=enqueue.status_code,
                        error=err,
                    )

                data = enqueue.json()
                job_id = data.get("jobId")
                if not job_id:
                    return KodiscResult(
                        success=False,
                        error=f"Kodisc enqueue response missing jobId: {data}",
                    )
                logger.info(f"[Kodisc] enqueued job {job_id} status={data.get('status')}")

                return await self._poll_job(client, job_id)

        except httpx.TimeoutException:
            return KodiscResult(success=False, error="Network timeout contacting Kodisc")
        except httpx.ConnectError as e:
            return KodiscResult(success=False, error=f"Cannot reach Kodisc: {e}")
        except Exception as e:
            logger.exception("[Kodisc] unexpected error in render()")
            return KodiscResult(success=False, error=f"{type(e).__name__}: {e}")

    async def _poll_job(self, client: httpx.AsyncClient, job_id: str) -> KodiscResult:
        interval = POLL_INTERVAL_START
        deadline = time.monotonic() + TOTAL_RENDER_BUDGET_SECONDS

        while True:
            if time.monotonic() > deadline:
                logger.error(f"[Kodisc] poll timeout for job {job_id}")
                return KodiscResult(
                    success=False,
                    job_id=job_id,
                    error=f"Render did not complete within {TOTAL_RENDER_BUDGET_SECONDS}s",
                )

            await asyncio.sleep(interval)
            interval = min(interval * 1.3, POLL_INTERVAL_MAX)

            try:
                poll = await client.get(
                    f"{KODISC_API_URL}/render/{job_id}",
                    headers=self._headers(),
                    timeout=POLL_TIMEOUT,
                )
            except (httpx.TimeoutException, httpx.ConnectError) as e:
                logger.warning(f"[Kodisc] poll network hiccup for {job_id}: {e}; retrying")
                continue

            if poll.status_code in (401, 403, 404):
                raw = poll.text[:300]
                logger.error(f"[Kodisc] poll HTTP {poll.status_code} for {job_id}: {raw}")
                return KodiscResult(
                    success=False,
                    status_code=poll.status_code,
                    job_id=job_id,
                    error=self._format_error(poll.status_code, raw),
                )

            if poll.status_code != 200:
                logger.warning(f"[Kodisc] poll HTTP {poll.status_code} for {job_id}; continuing")
                continue

            j = poll.json()
            status = j.get("status")
            if status == "completed":
                result = j.get("result") or {}
                logger.info(
                    f"[Kodisc] job {job_id} completed in {j.get('durationMs')}ms "
                    f"cost={j.get('creditsCost')}"
                )
                return KodiscResult(
                    success=True,
                    job_id=job_id,
                    video_url=result.get("video"),
                    thumbnail_url=result.get("thumbnail"),
                    captions_url=result.get("captions"),
                    duration_ms=j.get("durationMs"),
                    credits_cost=j.get("creditsCost"),
                )
            if status == "failed":
                err = j.get("error") or "Render failed"
                logger.error(f"[Kodisc] job {job_id} failed: {err}")
                return KodiscResult(
                    success=False,
                    job_id=job_id,
                    error=str(err)[:500],
                )
            # still queued/running — keep polling

    async def get_credits(self) -> Optional[dict]:
        """GET /api/v2/me — returns dict with credit balance, or None on failure."""
        if not self.is_configured():
            return None
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.get(f"{KODISC_API_URL}/me", headers=self._headers())
                if resp.status_code == 200:
                    return resp.json()
                logger.warning(f"[Kodisc] /me HTTP {resp.status_code}: {resp.text[:200]}")
        except Exception as e:
            logger.warning(f"[Kodisc] /me error: {e}")
        return None

    @staticmethod
    def _format_error(status_code: int, raw: str) -> str:
        if status_code in (401, 403):
            return (
                f"HTTP {status_code} Unauthorized: Kodisc rejected the API key. "
                f"Verify KODISC_API_KEY in your env starts with kdsc_live_ and is active. "
                f"Response: {raw}"
            )
        if status_code == 402:
            return f"HTTP 402: Insufficient credits. Top up at the Kodisc dashboard. Response: {raw}"
        if status_code == 404:
            return f"HTTP 404: jobId not found or not owned by this key. Response: {raw}"
        if status_code == 400:
            return f"HTTP 400: Bad request. Response: {raw}"
        return f"HTTP {status_code}: {raw}"
