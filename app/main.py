"""Paper to Video: FastAPI entrypoint. Vercel auto-detects `app` in app/main.py."""
import logging

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.routers.jobs import router as jobs_router

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

app = FastAPI(
    title="Paper to Video API",
    description="Turn a research paper PDF into a narrated explainer video.",
    version="0.2.0",
)
app.include_router(jobs_router)


@app.get("/", include_in_schema=False)
async def root():
    return FileResponse(str(settings.static_dir / "index.html"))


@app.get("/health")
async def health():
    return {"status": "healthy", "version": "0.2.0"}


# Declared after the routes so API routes always win. On Vercel these files are promoted to the CDN.
if settings.static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(settings.static_dir)), name="static")
