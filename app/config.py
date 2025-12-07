from pathlib import Path

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    MISTRAL_API_KEY: str = ""
    ANTHROPIC_API_KEY: str = ""
    ELEVENLABS_API_KEY: str = ""
    SHOTSTACK_API_KEY: str = ""
    SHOTSTACK_ENV: str = "stage"

    # Paths
    BASE_DIR: Path = Path(__file__).parent.parent
    UPLOADS_DIR: Path = BASE_DIR / "uploads"
    OUTPUTS_DIR: Path = BASE_DIR / "outputs"

    class Config:
        env_file = ".env"


settings = Settings()
