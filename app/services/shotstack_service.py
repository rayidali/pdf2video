"""
Shotstack: stitch slide videos and voiceovers into one mp4.

Each video clip's length is set to its voiceover duration. When that is longer than the
clip itself, Shotstack holds the last frame, so the generated scenes must end on their
final composed frame (never a fade-out). No local trimming, no ffmpeg.

submit_render() and check_render_status() are each one HTTP call, suitable for serverless.
"""
import logging
from dataclasses import dataclass
from typing import List, Optional

import httpx

logger = logging.getLogger(__name__)

SHOTSTACK_STAGE_URL = "https://api.shotstack.io/stage"
SHOTSTACK_PROD_URL = "https://api.shotstack.io/v1"


@dataclass
class SlideAsset:
    slide_number: int
    video_url: str
    audio_url: Optional[str] = None
    audio_duration: Optional[float] = None
    fallback_duration: float = 8.0   # used when there is no voiceover
    title: Optional[str] = None


@dataclass
class ShotstackResult:
    success: bool
    video_url: Optional[str] = None
    render_id: Optional[str] = None
    error: Optional[str] = None
    status: Optional[str] = None


class ShotstackService:
    def __init__(self, api_key: str, env: str = "stage"):
        self.api_key = api_key
        self.env = env
        self.base_url = SHOTSTACK_PROD_URL if env == "v1" else SHOTSTACK_STAGE_URL

    def is_configured(self) -> bool:
        return bool(self.api_key)

    @staticmethod
    def build_timeline(slides: List[SlideAsset]) -> dict:
        video_clips, audio_clips = [], []
        t = 0.0
        for s in sorted(slides, key=lambda x: x.slide_number):
            length = s.audio_duration if (s.audio_url and s.audio_duration) else s.fallback_duration
            length = round(max(length, 1.0), 3)
            video_clips.append({
                "asset": {"type": "video", "src": s.video_url, "volume": 0},
                "start": round(t, 3),
                "length": length,
            })
            if s.audio_url and s.audio_duration:
                audio_clips.append({
                    "asset": {"type": "audio", "src": s.audio_url, "volume": 1.0},
                    "start": round(t, 3),
                    "length": round(s.audio_duration, 3),
                })
            t += length
        tracks = []
        if audio_clips:
            tracks.append({"clips": audio_clips})
        tracks.append({"clips": video_clips})
        return {"background": "#000000", "tracks": tracks}

    def build_edit(self, slides: List[SlideAsset], resolution: str = "hd", fps: int = 25) -> dict:
        return {"timeline": self.build_timeline(slides), "output": {"format": "mp4", "resolution": resolution, "fps": fps}}

    async def submit_render(self, slides: List[SlideAsset]) -> ShotstackResult:
        if not self.is_configured():
            return ShotstackResult(success=False, error="Shotstack API key not configured")
        if not slides:
            return ShotstackResult(success=False, error="No slides provided")
        edit = self.build_edit(slides)
        logger.info(f"[Shotstack] submitting {len(slides)} clips to {self.env}")
        try:
            async with httpx.AsyncClient(timeout=60) as client:
                response = await client.post(
                    f"{self.base_url}/render", json=edit,
                    headers={"x-api-key": self.api_key, "Content-Type": "application/json"},
                )
        except httpx.HTTPError as e:
            return ShotstackResult(success=False, error=f"Shotstack network error: {e}")
        if response.status_code != 201:
            logger.error(f"[Shotstack] submit HTTP {response.status_code}: {response.text[:300]}")
            return ShotstackResult(success=False, error=f"Shotstack error {response.status_code}: {response.text[:300]}")
        render_id = (response.json().get("response") or {}).get("id")
        if not render_id:
            return ShotstackResult(success=False, error="No render id in Shotstack response")
        return ShotstackResult(success=True, render_id=render_id, status="queued")

    async def check_render_status(self, render_id: str) -> ShotstackResult:
        if not self.is_configured():
            return ShotstackResult(success=False, error="Shotstack API key not configured")
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.get(f"{self.base_url}/render/{render_id}", headers={"x-api-key": self.api_key})
        except httpx.HTTPError as e:
            return ShotstackResult(success=True, render_id=render_id, status="rendering", error=f"poll error; retry: {e}")
        if response.status_code != 200:
            return ShotstackResult(success=False, render_id=render_id, error=f"Shotstack error {response.status_code}: {response.text[:300]}")
        body = response.json().get("response") or {}
        status = body.get("status")
        if status == "done":
            return ShotstackResult(success=True, render_id=render_id, status="done", video_url=body.get("url"))
        if status == "failed":
            return ShotstackResult(success=False, render_id=render_id, status="failed", error=body.get("error") or "Render failed")
        return ShotstackResult(success=True, render_id=render_id, status=status or "rendering")
