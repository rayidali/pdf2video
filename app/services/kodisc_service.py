"""
Kodisc API Service

Integrates with Kodisc (https://kodisc.com) for AI-powered Manim video generation.

API Docs: https://docs.kodisc.com/api-reference/generating-videos

Pricing:
- Video Generation: 10 credits = $0.025 per video
- Image Generation: 3 credits = $0.0075 per image
- Video Rendering: 1 credit = $0.0025

IMPORTANT: Kodisc requires multipart/form-data, NOT json or urlencoded.
Use files= parameter in httpx to send proper multipart.
"""

import httpx
import logging
from typing import Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)

KODISC_API_URL = "https://api.kodisc.com"
DEFAULT_TIMEOUT = 180  # 3 minutes - video generation can take time


@dataclass
class KodiscResult:
    """Result from Kodisc API call."""
    success: bool
    video_url: Optional[str] = None
    code: Optional[str] = None
    error: Optional[str] = None


class KodiscService:
    """
    Service to generate Manim videos using Kodisc API.

    This is a hosted solution - no need to run your own Manim server.
    """

    def __init__(self, api_key: str, timeout: int = DEFAULT_TIMEOUT):
        """
        Initialize the Kodisc service.

        Args:
            api_key: Kodisc API key (starts with 'kodisc_')
            timeout: Request timeout in seconds
        """
        self.api_key = api_key
        self.timeout = timeout

        if not api_key or not api_key.startswith("kodisc_"):
            logger.warning("Kodisc API key missing or invalid format")

    def is_configured(self) -> bool:
        """Check if the service is properly configured with an API key."""
        return bool(self.api_key and self.api_key.startswith("kodisc_"))

    async def generate_video(
        self,
        prompt: str,
        aspect_ratio: str = "16:9",
        voiceover: bool = False,
        voice: str = "en-US-AriaNeural",
        fps: int = 30,
        colors: Optional[dict] = None
    ) -> KodiscResult:
        """
        Generate a video from a text prompt using Kodisc API.

        Args:
            prompt: Text description of the animation to create (keep it simple!)
            aspect_ratio: "16:9" (default) or "9:16" (mobile)
            voiceover: Whether to add AI voiceover
            voice: Azure voice ID for voiceover (e.g., "en-US-AriaNeural")
            fps: Framerate of the video
            colors: Optional color scheme dict with keys:
                    "primary", "secondary", "background", "text" (hex codes)

        Returns:
            KodiscResult with video_url and code on success

        Cost: 10 credits ($0.025) per video
        """
        if not self.is_configured():
            return KodiscResult(
                success=False,
                error="Kodisc API key not configured. Add KODISC_API_KEY to .env"
            )

        logger.info(f"Generating video via Kodisc API...")
        logger.info(f"Prompt ({len(prompt)} chars): {prompt[:100]}...")

        try:
            # IMPORTANT: Kodisc requires multipart/form-data
            # Use files= with (None, value) tuples to send as multipart
            files = {
                "apiKey": (None, self.api_key),
                "prompt": (None, prompt),
                "aspectRatio": (None, aspect_ratio),
                "fps": (None, str(fps)),
            }

            if voiceover:
                files["voiceover"] = (None, "true")
                files["voice"] = (None, voice)

            if colors:
                import json
                files["colors"] = (None, json.dumps(colors))

            # === DEBUG: Log the exact payload being sent ===
            debug_payload = {k: v[1][:100] + "..." if len(v[1]) > 100 else v[1]
                           for k, v in files.items() if k != "apiKey"}
            logger.info(f"[Kodisc] Sending payload: {debug_payload}")

            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    f"{KODISC_API_URL}/generate/video",
                    files=files  # multipart/form-data
                )

                # === CRITICAL: Check status code BEFORE parsing JSON ===
                if response.status_code != 200:
                    raw_text = response.text[:500]  # First 500 chars
                    logger.error(f"[Kodisc] HTTP {response.status_code}: {raw_text}")
                    return KodiscResult(
                        success=False,
                        error=f"HTTP {response.status_code}: {raw_text}"
                    )

                try:
                    data = response.json()
                except Exception as json_err:
                    logger.error(f"[Kodisc] Failed to parse JSON: {json_err}")
                    logger.error(f"[Kodisc] Raw response: {response.text[:500]}")
                    return KodiscResult(
                        success=False,
                        error=f"Invalid JSON response: {response.text[:200]}"
                    )

                # Log the full response for debugging (without API key)
                debug_data = {k: v for k, v in data.items() if k != "apiKey"}
                logger.info(f"[Kodisc] Response: {debug_data}")

                if data.get("success"):
                    video_url = data.get("video")
                    code = data.get("code")
                    logger.info(f"[Kodisc] Video generated successfully: {video_url}")
                    return KodiscResult(
                        success=True,
                        video_url=video_url,
                        code=code
                    )
                else:
                    error_msg = data.get("error", "Unknown error from Kodisc API")
                    # === CRITICAL: Log the Manim traceback if present ===
                    if "logs" in data:
                        logger.error(f"[Kodisc] MANIM LOGS: {data['logs']}")
                    if "traceback" in data:
                        logger.error(f"[Kodisc] TRACEBACK: {data['traceback']}")
                    if "code" in data:
                        # Sometimes they return the broken code even on failure
                        logger.error(f"[Kodisc] BROKEN CODE: {data['code'][:500]}...")
                    logger.error(f"[Kodisc] API error: {error_msg}")
                    return KodiscResult(
                        success=False,
                        error=error_msg
                    )

        except httpx.TimeoutException:
            logger.error(f"Kodisc API timeout after {self.timeout}s")
            return KodiscResult(
                success=False,
                error=f"Request timed out after {self.timeout} seconds"
            )
        except httpx.ConnectError as e:
            logger.error(f"Cannot connect to Kodisc API: {e}")
            return KodiscResult(
                success=False,
                error=f"Cannot connect to Kodisc API: {e}"
            )
        except Exception as e:
            logger.error(f"Kodisc API error: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return KodiscResult(
                success=False,
                error=str(e)
            )

    async def generate_image(
        self,
        prompt: str,
        aspect_ratio: str = "16:9",
        colors: Optional[dict] = None
    ) -> KodiscResult:
        """
        Generate a static image from a text prompt.

        Cost: 3 credits ($0.0075) per image
        """
        if not self.is_configured():
            return KodiscResult(
                success=False,
                error="Kodisc API key not configured"
            )

        logger.info(f"Generating image via Kodisc API...")

        try:
            # Use files= for multipart/form-data
            files = {
                "apiKey": (None, self.api_key),
                "prompt": (None, prompt),
                "aspectRatio": (None, aspect_ratio),
            }

            if colors:
                import json
                files["colors"] = (None, json.dumps(colors))

            async with httpx.AsyncClient(timeout=60) as client:
                response = await client.post(
                    f"{KODISC_API_URL}/generate/image",
                    files=files
                )

                data = response.json()

                if data.get("success"):
                    return KodiscResult(
                        success=True,
                        video_url=data.get("image"),  # It's an image URL
                        code=data.get("code")
                    )
                else:
                    return KodiscResult(
                        success=False,
                        error=data.get("error", "Unknown error")
                    )

        except Exception as e:
            logger.error(f"Kodisc image generation error: {e}")
            return KodiscResult(
                success=False,
                error=str(e)
            )
