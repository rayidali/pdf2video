import os
from pathlib import Path

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    MISTRAL_API_KEY: str = ""
    ANTHROPIC_API_KEY: str = ""
    ELEVENLABS_API_KEY: str = ""
    SHOTSTACK_API_KEY: str = ""
    SHOTSTACK_ENV: str = "stage"

    # Paths - use /tmp for Vercel serverless, local dirs otherwise
    BASE_DIR: Path = Path(__file__).parent.parent

    @property
    def UPLOADS_DIR(self) -> Path:
        """Use /tmp on Vercel (serverless), local uploads/ otherwise."""
        if os.environ.get("VERCEL"):
            return Path("/tmp/uploads")
        return self.BASE_DIR / "uploads"

    @property
    def OUTPUTS_DIR(self) -> Path:
        """Use /tmp on Vercel (serverless), local outputs/ otherwise."""
        if os.environ.get("VERCEL"):
            return Path("/tmp/outputs")
        return self.BASE_DIR / "outputs"

    class Config:
        env_file = ".env"


settings = Settings()
