from pathlib import Path

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    MISTRAL_API_KEY: str = ""
    ANTHROPIC_API_KEY: str = ""
    ELEVENLABS_API_KEY: str = ""
    SHOTSTACK_API_KEY: str = ""
    SHOTSTACK_ENV: str = "stage"

    # Kodisc API for video generation (hosted - no self-hosting needed)
    # Get API key from: https://kodisc.com
    # Cost: 10 credits ($0.025) per video
    KODISC_API_KEY: str = ""

    # ElevenLabs TTS settings
    ELEVENLABS_VOICE_ID: str = "pqHfZKP75CvOlQylNhV4"  # George
    ELEVENLABS_MODEL_ID: str = "eleven_turbo_v2_5"

    # Cloudflare R2 storage (S3-compatible)
    R2_ACCESS_KEY_ID: str = ""
    R2_SECRET_ACCESS_KEY: str = ""
    R2_ENDPOINT_URL: str = "https://c0ebff86d2b3187dd34b97c37df76da6.r2.cloudflarestorage.com"
    R2_BUCKET_NAME: str = "slides1"
    R2_PUBLIC_URL_BASE: str = "https://pub-34b1f2a534c64f48ad64ff0a3bd68992.r2.dev"

    # Generative Manim API for rendering (self-hosted alternative)
    GENERATIVE_MANIM_API_URL: str = "http://127.0.0.1:8080"
    RENDER_ENABLED: bool = False

    # Paths
    BASE_DIR: Path = Path(__file__).parent.parent
    UPLOADS_DIR: Path = BASE_DIR / "uploads"
    OUTPUTS_DIR: Path = BASE_DIR / "outputs"

    class Config:
        env_file = ".env"


settings = Settings()
