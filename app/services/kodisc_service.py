"""
Kodisc API Service

Integrates with Kodisc (https://kodisc.com) for AI-powered Manim video generation.

API Docs: https://docs.kodisc.com/api-reference/generating-videos

Pricing:
- Video Generation: 10 credits = $0.025 per video
- Image Generation: 3 credits = $0.0075 per image
- Video Rendering: 1 credit = $0.0025

Key features:
- No self-hosting required (hosted API)
- Returns video URL directly
- Also returns generated Manim code
- Supports voiceover generation
"""

import httpx
import logging
from typing import Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)

KODISC_API_URL = "https://api.kodisc.com"
DEFAULT_TIMEOUT = 120  # 2 minutes - video generation can take time


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
            prompt: Text description of the animation to create
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
        logger.debug(f"Prompt: {prompt[:200]}...")

        try:
            # Kodisc uses FormData, not JSON
            form_data = {
                "apiKey": self.api_key,
                "prompt": prompt,
                "aspectRatio": aspect_ratio,
                "fps": str(fps),
            }

            if voiceover:
                form_data["voiceover"] = "true"
                form_data["voice"] = voice

            if colors:
                import json
                form_data["colors"] = json.dumps(colors)

            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    f"{KODISC_API_URL}/generate/video",
                    data=form_data  # FormData, not json
                )

                data = response.json()

                if data.get("success"):
                    video_url = data.get("video")
                    code = data.get("code")
                    logger.info(f"Video generated successfully: {video_url}")
                    return KodiscResult(
                        success=True,
                        video_url=video_url,
                        code=code
                    )
                else:
                    error_msg = data.get("error", "Unknown error from Kodisc API")
                    logger.error(f"Kodisc API error: {error_msg}")
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
            form_data = {
                "apiKey": self.api_key,
                "prompt": prompt,
                "aspectRatio": aspect_ratio,
            }

            if colors:
                import json
                form_data["colors"] = json.dumps(colors)

            async with httpx.AsyncClient(timeout=60) as client:
                response = await client.post(
                    f"{KODISC_API_URL}/generate/image",
                    data=form_data
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
