"""
Shotstack Video Editing API Service

Combines multiple video clips with audio voiceovers into a single final video.
Uses freeze-frame technique to extend short clips to match longer voiceovers.

API Docs: https://shotstack.io/docs/api/
Pricing: https://shotstack.io/pricing/
"""

import httpx
import asyncio
import logging
from typing import Optional, List
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# Shotstack API endpoints
SHOTSTACK_STAGE_URL = "https://api.shotstack.io/stage"
SHOTSTACK_PROD_URL = "https://api.shotstack.io/v1"

# Polling configuration
POLL_INTERVAL_SECONDS = 5
MAX_POLL_ATTEMPTS = 120  # 10 minutes max wait


@dataclass
class SlideAsset:
    """Video and audio assets for a single slide."""
    slide_number: int
    video_url: str
    audio_url: Optional[str] = None
    audio_duration: Optional[float] = None  # seconds
    title: Optional[str] = None


@dataclass
class ShotstackResult:
    """Result from Shotstack render."""
    success: bool
    video_url: Optional[str] = None
    render_id: Optional[str] = None
    error: Optional[str] = None
    status: Optional[str] = None


class ShotstackService:
    """
    Service to combine video clips + audio into final video using Shotstack API.

    Features:
    - Sequences multiple video clips on a timeline
    - Overlays voiceover audio for each clip
    - Uses freeze-frame (extends clip length beyond video duration)
    - Adds smooth transitions between clips
    """

    def __init__(self, api_key: str, env: str = "stage"):
        """
        Initialize Shotstack service.

        Args:
            api_key: Shotstack API key
            env: "stage" for sandbox (free), "v1" for production
        """
        self.api_key = api_key
        self.base_url = SHOTSTACK_STAGE_URL if env == "stage" else SHOTSTACK_PROD_URL

    def is_configured(self) -> bool:
        """Check if service is configured."""
        return bool(self.api_key)

    def _build_timeline(
        self,
        slides: List[SlideAsset],
        min_clip_duration: float = 5.0,
        estimated_video_duration: float = 7.0,
        trim_end: float = 2.0
    ) -> dict:
        """
        Build Shotstack timeline JSON from slide assets.

        Loops video clips to fill audio duration (avoids freezing on black frames).
        Trims the last 2s from each video to avoid fade-out black frames.

        Args:
            slides: List of SlideAsset with video/audio URLs
            min_clip_duration: Minimum clip duration if no audio
            estimated_video_duration: Estimated duration of Kodisc videos (for looping)
            trim_end: Seconds to trim from end of video (avoid fade-out)

        Returns:
            Timeline dict for Shotstack API
        """
        video_clips = []
        audio_clips = []
        current_time = 0.0

        # Effective video duration after trimming the end
        effective_video_duration = estimated_video_duration - trim_end

        for slide in slides:
            # Determine total duration needed for this slide
            total_duration = slide.audio_duration if slide.audio_duration else min_clip_duration

            # Loop video to fill audio duration (instead of freeze-frame)
            # This avoids showing a frozen black frame from fade-out
            slide_start = current_time
            time_filled = 0.0

            while time_filled < total_duration:
                remaining = total_duration - time_filled
                # Use shorter of: remaining time or effective video duration
                clip_length = min(remaining, effective_video_duration)

                video_clip = {
                    "asset": {
                        "type": "video",
                        "src": slide.video_url,
                        "volume": 0  # Mute original video audio
                    },
                    "start": slide_start + time_filled,
                    "length": clip_length
                }
                video_clips.append(video_clip)
                time_filled += clip_length

            # Audio clip (on separate track - top layer)
            if slide.audio_url and slide.audio_duration:
                audio_clip = {
                    "asset": {
                        "type": "audio",
                        "src": slide.audio_url,
                        "volume": 1.0
                    },
                    "start": current_time,
                    "length": slide.audio_duration
                }
                audio_clips.append(audio_clip)

            current_time += total_duration

        # Build timeline with tracks
        # Tracks are layered: first track is on top
        tracks = []

        # Audio track (top - so it's heard)
        if audio_clips:
            tracks.append({"clips": audio_clips})

        # Video track (bottom)
        tracks.append({"clips": video_clips})

        timeline = {
            "background": "#000000",
            "tracks": tracks
        }

        return timeline

    def _build_edit(
        self,
        slides: List[SlideAsset],
        resolution: str = "hd",
        fps: int = 25,
        format: str = "mp4"
    ) -> dict:
        """
        Build complete Shotstack edit JSON.

        Args:
            slides: List of SlideAsset
            resolution: "sd" (576p), "hd" (720p), "1080" (1080p)
            fps: Frames per second (25 default)
            format: Output format ("mp4", "gif", "webm")

        Returns:
            Complete edit dict for Shotstack API
        """
        timeline = self._build_timeline(slides)

        edit = {
            "timeline": timeline,
            "output": {
                "format": format,
                "resolution": resolution,
                "fps": fps
            }
        }

        return edit

    async def submit_render(self, slides: List[SlideAsset]) -> ShotstackResult:
        """
        Submit video edit to Shotstack for rendering.

        Args:
            slides: List of SlideAsset with video/audio URLs

        Returns:
            ShotstackResult with render_id for polling
        """
        if not self.is_configured():
            return ShotstackResult(
                success=False,
                error="Shotstack API key not configured"
            )

        if not slides:
            return ShotstackResult(
                success=False,
                error="No slides provided"
            )

        edit = self._build_edit(slides)

        logger.info(f"[Shotstack] Submitting render with {len(slides)} clips...")
        logger.debug(f"[Shotstack] Edit JSON: {edit}")

        try:
            async with httpx.AsyncClient(timeout=60) as client:
                response = await client.post(
                    f"{self.base_url}/render",
                    json=edit,
                    headers={
                        "x-api-key": self.api_key,
                        "Content-Type": "application/json"
                    }
                )

                if response.status_code != 201:
                    error_text = response.text
                    logger.error(f"[Shotstack] Submit failed: {response.status_code} - {error_text}")
                    return ShotstackResult(
                        success=False,
                        error=f"API error {response.status_code}: {error_text}"
                    )

                data = response.json()
                render_id = data.get("response", {}).get("id")

                if not render_id:
                    return ShotstackResult(
                        success=False,
                        error="No render ID in response"
                    )

                logger.info(f"[Shotstack] Render submitted: {render_id}")

                return ShotstackResult(
                    success=True,
                    render_id=render_id,
                    status="queued"
                )

        except httpx.TimeoutException:
            logger.error("[Shotstack] Request timeout")
            return ShotstackResult(success=False, error="Request timeout")
        except Exception as e:
            logger.error(f"[Shotstack] Error: {e}")
            return ShotstackResult(success=False, error=str(e))

    async def check_render_status(self, render_id: str) -> ShotstackResult:
        """
        Check the status of a render job.

        Args:
            render_id: The render ID from submit_render

        Returns:
            ShotstackResult with status and video_url if complete
        """
        if not self.is_configured():
            return ShotstackResult(
                success=False,
                error="Shotstack API key not configured"
            )

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.get(
                    f"{self.base_url}/render/{render_id}",
                    headers={"x-api-key": self.api_key}
                )

                if response.status_code != 200:
                    return ShotstackResult(
                        success=False,
                        render_id=render_id,
                        error=f"API error {response.status_code}: {response.text}"
                    )

                data = response.json()
                status = data.get("response", {}).get("status")
                video_url = data.get("response", {}).get("url")

                logger.info(f"[Shotstack] Render {render_id} status: {status}")

                if status == "done":
                    return ShotstackResult(
                        success=True,
                        render_id=render_id,
                        status=status,
                        video_url=video_url
                    )
                elif status == "failed":
                    error = data.get("response", {}).get("error", "Unknown error")
                    return ShotstackResult(
                        success=False,
                        render_id=render_id,
                        status=status,
                        error=error
                    )
                else:
                    # Still processing (queued, fetching, rendering, saving)
                    return ShotstackResult(
                        success=True,
                        render_id=render_id,
                        status=status
                    )

        except Exception as e:
            logger.error(f"[Shotstack] Status check error: {e}")
            return ShotstackResult(
                success=False,
                render_id=render_id,
                error=str(e)
            )

    async def render_and_wait(
        self,
        slides: List[SlideAsset],
        poll_interval: float = POLL_INTERVAL_SECONDS,
        max_attempts: int = MAX_POLL_ATTEMPTS
    ) -> ShotstackResult:
        """
        Submit render and wait for completion.

        This is a convenience method that handles the full flow:
        1. Submit the render
        2. Poll for status until complete/failed
        3. Return the final video URL

        Args:
            slides: List of SlideAsset
            poll_interval: Seconds between status checks
            max_attempts: Maximum polling attempts

        Returns:
            ShotstackResult with video_url if successful
        """
        # Submit the render
        submit_result = await self.submit_render(slides)

        if not submit_result.success or not submit_result.render_id:
            return submit_result

        render_id = submit_result.render_id

        # Poll for completion
        for attempt in range(max_attempts):
            await asyncio.sleep(poll_interval)

            status_result = await self.check_render_status(render_id)

            if status_result.status == "done":
                logger.info(f"[Shotstack] Render complete: {status_result.video_url}")
                return status_result
            elif status_result.status == "failed":
                logger.error(f"[Shotstack] Render failed: {status_result.error}")
                return status_result

            # Log progress
            if attempt % 6 == 0:  # Every 30 seconds
                logger.info(f"[Shotstack] Still rendering... status={status_result.status}, attempt={attempt+1}/{max_attempts}")

        # Timeout
        return ShotstackResult(
            success=False,
            render_id=render_id,
            error=f"Render timeout after {max_attempts * poll_interval} seconds"
        )
