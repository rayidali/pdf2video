import json
import logging
import shutil
import uuid
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from app.config import settings
from app.models.schemas import JobStatus, PresentationPlan
from app.services.ocr_service import MistralOCRService
from app.services.planning_service import PlanningService

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Paper to Video API",
    description="Convert research papers to animated explainer videos",
    version="0.1.0"
)

# Initialize services
ocr_service = MistralOCRService(settings.MISTRAL_API_KEY)
planning_service = PlanningService(settings.ANTHROPIC_API_KEY)

# Ensure directories exist
settings.UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
settings.OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)

# Mount static files
static_dir = settings.BASE_DIR / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

# In-memory job storage (replace with Redis in production)
jobs: dict[str, JobStatus] = {}


@app.get("/")
async def root():
    """Serve the frontend."""
    return FileResponse(str(settings.BASE_DIR / "static" / "index.html"))


@app.get("/health")
async def health_check():
    return {"status": "healthy", "version": "0.1.0"}


@app.post("/api/upload")
async def upload_pdf(file: UploadFile = File(...)):
    """
    Upload a PDF file and start OCR processing.
    Returns a job_id to track progress.
    """
    # Validate file type
    if not file.filename.endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are accepted")

    # Generate job ID
    job_id = str(uuid.uuid4())[:8]
    logger.info(f"Created new job: {job_id} for file: {file.filename}")

    # Create job directory
    job_dir = settings.UPLOADS_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)

    # Save uploaded file
    pdf_path = job_dir / file.filename
    with open(pdf_path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    logger.info(f"Saved PDF to: {pdf_path}")

    # Initialize job status
    jobs[job_id] = JobStatus(
        job_id=job_id,
        status="processing",
        step="uploaded"
    )

    return {"job_id": job_id, "status": "uploaded", "filename": file.filename}


@app.post("/api/process/{job_id}")
async def process_pdf(job_id: str):
    """
    Process the uploaded PDF through OCR.
    """
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")

    # Find the PDF file
    job_dir = settings.UPLOADS_DIR / job_id
    pdf_files = list(job_dir.glob("*.pdf"))

    if not pdf_files:
        raise HTTPException(status_code=404, detail="PDF file not found")

    pdf_path = pdf_files[0]
    logger.info(f"Processing PDF: {pdf_path}")

    # Update status
    jobs[job_id].step = "ocr_processing"

    try:
        # Run OCR
        markdown_content = await ocr_service.pdf_to_markdown(str(pdf_path))

        # Save markdown output
        output_dir = settings.OUTPUTS_DIR / job_id
        output_dir.mkdir(parents=True, exist_ok=True)

        markdown_path = output_dir / "paper.md"
        markdown_path.write_text(markdown_content)

        logger.info(f"Saved markdown to: {markdown_path}")

        # Update status
        jobs[job_id].step = "ocr_complete"

        return {
            "job_id": job_id,
            "status": "ocr_complete",
            "markdown_path": str(markdown_path),
            "markdown_preview": markdown_content[:500] + "..." if len(markdown_content) > 500 else markdown_content
        }

    except Exception as e:
        logger.error(f"OCR processing failed for job {job_id}: {str(e)}")
        jobs[job_id].status = "failed"
        jobs[job_id].error = str(e)
        raise HTTPException(status_code=500, detail=f"OCR processing failed: {str(e)}")


@app.get("/api/status/{job_id}")
async def get_job_status(job_id: str):
    """
    Get the current status of a job.
    """
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")

    return jobs[job_id]


@app.get("/api/markdown/{job_id}")
async def get_markdown(job_id: str):
    """
    Get the extracted markdown for a job.
    """
    markdown_path = settings.OUTPUTS_DIR / job_id / "paper.md"

    if not markdown_path.exists():
        raise HTTPException(status_code=404, detail="Markdown not found. Run OCR first.")

    return {"job_id": job_id, "markdown": markdown_path.read_text()}


@app.post("/api/plan/{job_id}")
async def create_plan(job_id: str):
    """
    Create a presentation plan from the extracted markdown using Claude.
    """
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")

    # Check if markdown exists
    markdown_path = settings.OUTPUTS_DIR / job_id / "paper.md"
    if not markdown_path.exists():
        raise HTTPException(status_code=400, detail="Markdown not found. Run OCR first.")

    logger.info(f"Creating presentation plan for job: {job_id}")
    jobs[job_id].step = "planning"

    try:
        markdown_content = markdown_path.read_text()
        plan = await planning_service.create_presentation_plan(markdown_content)

        # Save plan to file
        plan_path = settings.OUTPUTS_DIR / job_id / "plan.json"
        plan_path.write_text(plan.model_dump_json(indent=2))
        logger.info(f"Saved plan to: {plan_path}")

        jobs[job_id].step = "plan_complete"

        return {
            "job_id": job_id,
            "status": "plan_complete",
            "plan": plan.model_dump()
        }

    except Exception as e:
        logger.error(f"Planning failed for job {job_id}: {str(e)}")
        jobs[job_id].status = "failed"
        jobs[job_id].error = str(e)
        raise HTTPException(status_code=500, detail=f"Planning failed: {str(e)}")


@app.get("/api/plan/{job_id}")
async def get_plan(job_id: str):
    """
    Get the presentation plan for a job.
    """
    plan_path = settings.OUTPUTS_DIR / job_id / "plan.json"

    if not plan_path.exists():
        raise HTTPException(status_code=404, detail="Plan not found. Create a plan first.")

    plan_data = json.loads(plan_path.read_text())
    return {"job_id": job_id, "plan": plan_data}
