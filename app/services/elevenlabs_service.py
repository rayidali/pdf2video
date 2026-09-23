"""ElevenLabs text-to-speech. Returns MP3 bytes plus the real audio duration."""
import io
import logging
from dataclasses import dataclass
from typing import Optional

import httpx

logger = logging.getLogger(__name__)


@dataclass
class VoiceoverResult:
    success: bool
    audio_data: Optional[bytes] = None
    file_size_bytes: int = 0
    duration_seconds: float = 0.0
    error: Optional[str] = None


def mp3_duration_seconds(data: bytes) -> Optional[float]:
    """Exact duration from the MP3 frames (mutagen). None if the file cannot be parsed."""
    try:
        from mutagen.mp3 import MP3

        return float(MP3(io.BytesIO(data)).info.length)
    except Exception as e:  # pragma: no cover - depends on the bytes
        logger.warning(f"[TTS] could not read mp3 duration: {e}")
        return None


class ElevenLabsService:
    BASE_URL = "https://api.elevenlabs.io/v1"

    def __init__(self, api_key: str, voice_id: str = "pqHfZKP75CvOlQylNhV4", model_id: str = "eleven_turbo_v2_5"):
        self.api_key = api_key
        self.voice_id = voice_id
        self.model_id = model_id

    def is_configured(self) -> bool:
        return bool(self.api_key)

    @staticmethod
    def _estimate_duration_from_size(file_size_bytes: int, bitrate_bps: int = 128000) -> float:
        return (file_size_bytes * 8) / bitrate_bps if file_size_bytes > 0 else 0.0

    async def generate_voiceover(self, text: str, stability: float = 0.5, similarity_boost: float = 0.75) -> VoiceoverResult:
        if not self.is_configured():
            return VoiceoverResult(success=False, error="ElevenLabs API key not configured")
        if not text or not text.strip():
            return VoiceoverResult(success=False, error="Empty text provided")

        url = f"{self.BASE_URL}/text-to-speech/{self.voice_id}"
        headers = {"xi-api-key": self.api_key, "Content-Type": "application/json", "Accept": "audio/mpeg"}
        payload = {
            "text": text,
            "model_id": self.model_id,
            "voice_settings": {"stability": stability, "similarity_boost": similarity_boost},
        }
        logger.info(f"[TTS] {len(text)} chars")
        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                response = await client.post(url, headers=headers, json=payload)
        except httpx.TimeoutException:
            return VoiceoverResult(success=False, error="ElevenLabs request timed out")
        except httpx.HTTPError as e:
            return VoiceoverResult(success=False, error=f"ElevenLabs network error: {e}")

        if response.status_code != 200:
            detail = response.text[:300] if response.text else "Unknown error"
            logger.error(f"[TTS] HTTP {response.status_code}: {detail}")
            return VoiceoverResult(success=False, error=f"ElevenLabs error {response.status_code}: {detail}")

        audio = response.content
        duration = mp3_duration_seconds(audio) or self._estimate_duration_from_size(len(audio))
        logger.info(f"[TTS] {len(audio)} bytes, {duration:.1f}s")
        return VoiceoverResult(success=True, audio_data=audio, file_size_bytes=len(audio), duration_seconds=duration)
