from pathlib import Path

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    MISTRAL_API_KEY: str = ""
    ANTHROPIC_API_KEY: str = ""
    ELEVENLABS_API_KEY: str = ""
    SHOTSTACK_API_KEY: str = ""
    SHOTSTACK_ENV: str = "stage"

    # Generative Manim API for rendering
    # Default is local (run their API with Docker)
    # Or use hosted: https://api.generativemanim.com (if available)
    GENERATIVE_MANIM_API_URL: str = "http://127.0.0.1:8080"
    RENDER_ENABLED: bool = False  # Enable/disable real rendering

    # Paths
    BASE_DIR: Path = Path(__file__).parent.parent
    UPLOADS_DIR: Path = BASE_DIR / "uploads"
    OUTPUTS_DIR: Path = BASE_DIR / "outputs"

    class Config:
        env_file = ".env"


settings = Settings()
