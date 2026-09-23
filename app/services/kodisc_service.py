"""
Kodisc v2 client: Manim render-as-a-service.

Public API: https://kodisc.com/api/v2
- POST /render          enqueue a render (returns jobId)
- GET  /render/{jobId}  status: queued | running | completed | failed
- GET  /me              key info + credit balance

Auth: Authorization: Bearer kdsc_live_...   Body: application/json.
Kodisc only renders code you supply; we generate the Manim code with Claude.

Two entry points matter for the serverless flow: submit() and check(). Each is one short
HTTP call. render() chains them with a poll loop for local scripts and tests.
"""
import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

KODISC_API_URL = "https://kodisc.com/api/v2"
REQUEST_TIMEOUT = 30
POLL_INTERVAL_START = 2.0
POLL_INTERVAL_MAX = 5.0
TOTAL_RENDER_BUDGET_SECONDS = 240


@dataclass
class KodiscResult:
    success: bool                       # the HTTP call itself succeeded
    status: Optional[str] = None        # queued | running | completed | failed
    job_id: Optional[str] = None
    video_url: Optional[str] = None
    thumbnail_url: Optional[str] = None
    captions_url: Optional[str] = None
    error: Optional[str] = None
    status_code: Optional[int] = None
    duration_ms: Optional[int] = None
    credits_cost: Optional[int] = None

    @property
    def is_auth_error(self) -> bool:
        return self.status_code in (401, 403)

    @property
    def is_credits_error(self) -> bool:
        return self.status_code == 402

    @property
    def is_fatal(self) -> bool:
        return self.is_auth_error or self.is_credits_error

    @property
    def is_done(self) -> bool:
        return self.success and self.status == "completed"

    @property
    def is_failed(self) -> bool:
        return (not self.success) or self.status == "failed"


class KodiscService:
    def __init__(self, api_key: str, timeout: int = REQUEST_TIMEOUT):
        self.api_key = api_key or ""
        self.timeout = timeout
        if self.api_key and not self.api_key.startswith("kdsc_live_"):
            logger.warning("Kodisc API key does not start with 'kdsc_live_'; v1 keys no longer work.")

    def is_configured(self) -> bool:
        return bool(self.api_key and self.api_key.startswith("kdsc_live_"))

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    # ------------------------------------------------------------------ submit
    async def submit(
        self,
        code: str,
        class_name: str,
        quality: str = "medium",
        aspect_ratio: str = "16:9",
        fps: Optional[int] = None,
        webhook_url: Optional[str] = None,
        metadata: Optional[dict] = None,
    ) -> KodiscResult:
        """Enqueue a render. Returns job_id on success; does not wait."""
        if not self.is_configured():
            return KodiscResult(success=False, error="KODISC_API_KEY not configured (must start with kdsc_live_)")

        body: dict = {"code": code, "className": class_name, "quality": quality, "aspectRatio": aspect_ratio}
        if fps is not None:
            body["fps"] = fps
        if webhook_url:
            body["webhookUrl"] = webhook_url
        if metadata:
            body["metadata"] = metadata

        logger.info(f"[Kodisc] submit class={class_name} quality={quality} code_len={len(code)}")
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(f"{KODISC_API_URL}/render", json=body, headers=self._headers())
        except httpx.TimeoutException:
            return KodiscResult(success=False, error="Network timeout contacting Kodisc")
        except httpx.HTTPError as e:
            return KodiscResult(success=False, error=f"Cannot reach Kodisc: {e}")

        if resp.status_code not in (200, 201, 202):
            raw = resp.text[:500]
            logger.error(f"[Kodisc] submit HTTP {resp.status_code}: {raw}")
            return KodiscResult(success=False, status_code=resp.status_code, error=self._format_error(resp.status_code, raw))

        data = resp.json()
        job_id = data.get("jobId") or data.get("id")
        if not job_id:
            return KodiscResult(success=False, error=f"Kodisc response missing jobId: {str(data)[:200]}")
        status = data.get("status") or "queued"
        logger.info(f"[Kodisc] enqueued {job_id} status={status}")
        return KodiscResult(success=True, status=status, job_id=job_id)

    # ------------------------------------------------------------------- check
    async def check(self, job_id: str) -> KodiscResult:
        """One status call. Never loops."""
        if not self.is_configured():
            return KodiscResult(success=False, error="KODISC_API_KEY not configured")
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.get(f"{KODISC_API_URL}/render/{job_id}", headers=self._headers())
        except httpx.TimeoutException:
            return KodiscResult(success=True, status="running", job_id=job_id, error="poll timeout; retry")
        except httpx.HTTPError as e:
            return KodiscResult(success=True, status="running", job_id=job_id, error=f"poll error; retry: {e}")

        if resp.status_code != 200:
            raw = resp.text[:300]
            logger.error(f"[Kodisc] check HTTP {resp.status_code} for {job_id}: {raw}")
            return KodiscResult(success=False, status_code=resp.status_code, job_id=job_id, error=self._format_error(resp.status_code, raw))

        j = resp.json()
        status = j.get("status") or "running"
        if status == "completed":
            result = j.get("result") or {}
            return KodiscResult(
                success=True, status="completed", job_id=job_id,
                video_url=result.get("video") or j.get("video"),
                thumbnail_url=result.get("thumbnail") or j.get("thumbnail"),
                captions_url=result.get("captions"),
                duration_ms=j.get("durationMs"), credits_cost=j.get("creditsCost"),
            )
        if status == "failed":
            err = j.get("error") or (j.get("result") or {}).get("error") or "Render failed"
            return KodiscResult(success=True, status="failed", job_id=job_id, error=str(err)[:1500])
        return KodiscResult(success=True, status=status, job_id=job_id)

    # ------------------------------------------------------------------ render
    async def render(self, code: str, class_name: str, quality: str = "medium", aspect_ratio: str = "16:9") -> KodiscResult:
        """submit + poll until done. For scripts and tests, not for serverless handlers."""
        sub = await self.submit(code, class_name, quality=quality, aspect_ratio=aspect_ratio)
        if not sub.success:
            return sub
        interval = POLL_INTERVAL_START
        deadline = time.monotonic() + TOTAL_RENDER_BUDGET_SECONDS
        while time.monotonic() < deadline:
            await asyncio.sleep(interval)
            interval = min(interval * 1.3, POLL_INTERVAL_MAX)
            res = await self.check(sub.job_id)
            if res.is_done or res.is_failed:
                return res
        return KodiscResult(success=False, job_id=sub.job_id, error=f"Render did not complete within {TOTAL_RENDER_BUDGET_SECONDS}s")

    async def get_credits(self) -> Optional[dict]:
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
            return f"HTTP {status_code}: Kodisc rejected the API key. It must start with kdsc_live_ and be active. {raw}"
        if status_code == 402:
            return f"HTTP 402: Kodisc credits exhausted. Top up at kodisc.com. {raw}"
        if status_code == 404:
            return f"HTTP 404: Kodisc job not found for this key. {raw}"
        if status_code == 429:
            return f"HTTP 429: Kodisc rate limit. {raw}"
        return f"HTTP {status_code}: {raw}"
