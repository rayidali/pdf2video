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
