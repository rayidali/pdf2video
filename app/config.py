"""Application settings. Everything comes from environment variables or a local .env file.

Nothing here writes to the repo directory: on Vercel only /tmp is writable and it is ephemeral.
"""
import os
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent
ON_VERCEL = bool(os.environ.get("VERCEL"))


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Anthropic (planning + Manim code generation)
    ANTHROPIC_API_KEY: str = ""
    PLAN_MODEL: str = "claude-opus-5"
    CODE_MODEL: str = "claude-opus-5"

    # Mistral OCR
    MISTRAL_API_KEY: str = ""

    # Kodisc v2 (Manim render-as-a-service). Keys start with kdsc_live_
    KODISC_API_KEY: str = ""
    KODISC_QUALITY: str = "medium"

    # ElevenLabs TTS
    ELEVENLABS_API_KEY: str = ""
    ELEVENLABS_VOICE_ID: str = "pqHfZKP75CvOlQylNhV4"  # George
    ELEVENLABS_MODEL_ID: str = "eleven_turbo_v2_5"

    # Cloudflare R2 (S3-compatible). Public bucket for mp3s that Shotstack fetches.
    R2_ACCESS_KEY_ID: str = ""
    R2_SECRET_ACCESS_KEY: str = ""
    R2_ENDPOINT_URL: str = ""
    R2_BUCKET_NAME: str = ""
    R2_PUBLIC_URL_BASE: str = ""

    # Shotstack. "stage" = free sandbox with watermark, "v1" = production.
    SHOTSTACK_API_KEY: str = ""
    SHOTSTACK_ENV: str = "stage"

    # Persistence. DATABASE_URL (Postgres) on Vercel; SQLite file locally.
    DATABASE_URL: str = ""
    SQLITE_PATH: str = ""

    # Demo protection. If RUN_PASSCODE is set, every POST needs header X-Passcode.
    RUN_PASSCODE: str = ""
    # JSON list of {"title": ..., "url": ...} shown as a gallery on the landing page.
    SAMPLE_VIDEOS: str = "[]"
    MAX_UPLOAD_MB: int = 25

    @property
    def sqlite_path(self) -> Path:
        if self.SQLITE_PATH:
            return Path(self.SQLITE_PATH)
        if ON_VERCEL:
            return Path("/tmp/pdf2video.db")
        return BASE_DIR / "pdf2video.db"

    @property
    def static_dir(self) -> Path:
        return BASE_DIR / "static"


settings = Settings()
