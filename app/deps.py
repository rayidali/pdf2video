"""Singleton service instances. Routers import this module and access attributes at call
time (deps.ocr, deps.store, ...) so tests can swap in fakes with monkeypatch."""
from app.config import settings
from app.services.elevenlabs_service import ElevenLabsService
from app.services.kodisc_service import KodiscService
from app.services.manim_service import ManimService
from app.services.ocr_service import MistralOCRService
from app.services.planning_service import PlanningService
from app.services.r2_service import R2Service
from app.services.shotstack_service import ShotstackService
from app.store import build_store

ocr = MistralOCRService(settings.MISTRAL_API_KEY)
planner = PlanningService(settings.ANTHROPIC_API_KEY, model=settings.PLAN_MODEL)
manim = ManimService(settings.ANTHROPIC_API_KEY, model=settings.CODE_MODEL)
kodisc = KodiscService(settings.KODISC_API_KEY)
tts = ElevenLabsService(
    api_key=settings.ELEVENLABS_API_KEY,
    voice_id=settings.ELEVENLABS_VOICE_ID,
    model_id=settings.ELEVENLABS_MODEL_ID,
)
r2 = R2Service(
    access_key_id=settings.R2_ACCESS_KEY_ID,
    secret_access_key=settings.R2_SECRET_ACCESS_KEY,
    endpoint_url=settings.R2_ENDPOINT_URL,
    bucket_name=settings.R2_BUCKET_NAME,
    public_url_base=settings.R2_PUBLIC_URL_BASE,
)
shotstack = ShotstackService(api_key=settings.SHOTSTACK_API_KEY, env=settings.SHOTSTACK_ENV)
store = build_store(settings.database_url, settings.sqlite_path)


def service_status() -> dict:
    return {
        "text_extraction": "pypdf",
        "mistral_ocr_fallback": ocr.is_configured(),
        "anthropic": planner.is_configured(),
        "kodisc": kodisc.is_configured(),
        "elevenlabs": tts.is_configured(),
        "r2": r2.is_configured(),
        "shotstack": shotstack.is_configured(),
        "shotstack_env": settings.SHOTSTACK_ENV,
        "database": "postgres" if settings.database_url else "sqlite",
    }
