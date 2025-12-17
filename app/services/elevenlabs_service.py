"""
ElevenLabs Text-to-Speech Service

Generates voiceover audio from text scripts using ElevenLabs API.
"""

import logging
from dataclasses import dataclass
from typing import Optional

import httpx

logger = logging.getLogger(__name__)


@dataclass
class VoiceoverResult:
    """Result from voiceover generation."""
    success: bool
    audio_data: Optional[bytes] = None  # Raw MP3 bytes
    file_size_bytes: int = 0
    duration_seconds: float = 0.0
    error: Optional[str] = None


class ElevenLabsService:
    """Service for generating voiceovers using ElevenLabs API."""

    BASE_URL = "https://api.elevenlabs.io/v1"

    def __init__(
        self,
        api_key: str,
        voice_id: str = "pqHfZKP75CvOlQylNhV4",  # George
        model_id: str = "eleven_turbo_v2_5"
    ):
        self.api_key = api_key
        self.voice_id = voice_id
        self.model_id = model_id

    def is_configured(self) -> bool:
        """Check if service is configured with API key."""
        return bool(self.api_key)

    def _estimate_duration_from_size(self, file_size_bytes: int, bitrate_bps: int = 128000) -> float:
        """
        Estimate audio duration from file size.

        Formula: duration = (file_size_bytes * 8) / bitrate_bps
        Default bitrate for ElevenLabs MP3 is ~128kbps
        """
        if file_size_bytes <= 0:
            return 0.0
        return (file_size_bytes * 8) / bitrate_bps

    async def generate_voiceover(
        self,
        text: str,
        stability: float = 0.5,
        similarity_boost: float = 0.75
    ) -> VoiceoverResult:
        """
        Generate voiceover audio from text.

        Args:
            text: The script text to convert to speech
            stability: Voice stability (0.0-1.0)
            similarity_boost: Voice similarity boost (0.0-1.0)

        Returns:
            VoiceoverResult with audio_data (MP3 bytes) and metadata
        """
        if not self.is_configured():
            return VoiceoverResult(
                success=False,
                error="ElevenLabs API key not configured"
            )

        if not text or not text.strip():
            return VoiceoverResult(
                success=False,
                error="Empty text provided"
            )

        url = f"{self.BASE_URL}/text-to-speech/{self.voice_id}"

        headers = {
            "xi-api-key": self.api_key,
            "Content-Type": "application/json",
            "Accept": "audio/mpeg"
        }

        payload = {
            "text": text,
            "model_id": self.model_id,
            "voice_settings": {
                "stability": stability,
                "similarity_boost": similarity_boost
            }
        }

        logger.info(f"Generating voiceover for {len(text)} chars of text...")

        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                response = await client.post(url, headers=headers, json=payload)

                if response.status_code != 200:
                    error_detail = response.text[:500] if response.text else "Unknown error"
                    logger.error(f"ElevenLabs API error: {response.status_code} - {error_detail}")
                    return VoiceoverResult(
                        success=False,
                        error=f"API error {response.status_code}: {error_detail}"
                    )

                audio_data = response.content
                file_size = len(audio_data)
                duration = self._estimate_duration_from_size(file_size)

                logger.info(f"Voiceover generated: {file_size} bytes, ~{duration:.1f}s estimated duration")

                return VoiceoverResult(
                    success=True,
                    audio_data=audio_data,
                    file_size_bytes=file_size,
                    duration_seconds=duration
                )

        except httpx.TimeoutException:
            logger.error("ElevenLabs API timeout")
            return VoiceoverResult(
                success=False,
                error="API request timed out"
            )
        except Exception as e:
            logger.error(f"ElevenLabs API error: {e}")
            return VoiceoverResult(
                success=False,
                error=str(e)
            )
