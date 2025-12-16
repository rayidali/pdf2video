import json
import logging
import shutil
import uuid
from pathlib import Path

import asyncio
from fastapi import FastAPI, File, HTTPException, UploadFile, BackgroundTasks
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from app.config import settings
from app.models.schemas import JobStatus, PresentationPlan, SlideContent
from app.services.ocr_service import MistralOCRService
from app.services.planning_service import PlanningService
from app.services.manim_service import ManimService
from app.services.render_service import GenerativeManimService
from app.services.kodisc_service import KodiscService

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
manim_service = ManimService(settings.ANTHROPIC_API_KEY)
render_service = GenerativeManimService(settings.GENERATIVE_MANIM_API_URL)
kodisc_service = KodiscService(settings.KODISC_API_KEY)

# Ensure directories exist
settings.UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
settings.OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)

# Mount static files
static_dir = settings.BASE_DIR / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

# In-memory job storage (replace with Redis in production)
jobs: dict[str, JobStatus] = {}

# Track background generation tasks
generation_tasks: dict[str, dict] = {}  # job_id -> {status, progress, results, cancel_flag}


@app.get("/")
async def root():
    """Serve the frontend."""
    return FileResponse(str(settings.BASE_DIR / "static" / "index.html"))


@app.get("/health")
async def health_check():
    return {"status": "healthy", "version": "0.1.0"}


# ============================================
# JOB DISCOVERY & RESUME ENDPOINTS
# These allow resuming jobs after server restart
# without re-running API calls (saves credits!)
# ============================================

@app.get("/api/jobs")
async def list_jobs():
    """
    List all jobs that have cached data on disk.
    This allows resuming jobs after server restart without re-running the pipeline.

    Use this to:
    - See all previous jobs
    - Find jobs to resume testing
    - Avoid re-running OCR/planning/manim generation
    """
    discovered_jobs = []

    # Scan outputs directory for existing jobs
    if settings.OUTPUTS_DIR.exists():
        for job_dir in settings.OUTPUTS_DIR.iterdir():
            if job_dir.is_dir():
                job_id = job_dir.name
                job_info = {
                    "job_id": job_id,
                    "has_markdown": (job_dir / "paper.md").exists(),
                    "has_plan": (job_dir / "plan.json").exists(),
                    "has_manim": (job_dir / "slides" / "manifest.json").exists(),
                }

                # Determine the furthest completed step
                if job_info["has_manim"]:
                    job_info["completed_step"] = "manim_complete"
                elif job_info["has_plan"]:
                    job_info["completed_step"] = "plan_complete"
                elif job_info["has_markdown"]:
                    job_info["completed_step"] = "ocr_complete"
                else:
                    job_info["completed_step"] = "unknown"

                # Get slide count if manim exists
                if job_info["has_manim"]:
                    try:
                        manifest = json.loads((job_dir / "slides" / "manifest.json").read_text())
                        job_info["slides_count"] = len(manifest)
                    except Exception:
                        job_info["slides_count"] = 0

                # Check for uploaded PDF
                upload_dir = settings.UPLOADS_DIR / job_id
                if upload_dir.exists():
                    pdf_files = list(upload_dir.glob("*.pdf"))
                    job_info["has_pdf"] = len(pdf_files) > 0
                    if pdf_files:
                        job_info["pdf_name"] = pdf_files[0].name
                else:
                    job_info["has_pdf"] = False

                discovered_jobs.append(job_info)

    # Sort by job_id (most recent first if using UUID)
    discovered_jobs.sort(key=lambda x: x["job_id"], reverse=True)

    return {
        "jobs": discovered_jobs,
        "count": len(discovered_jobs),
        "tip": "Use POST /api/jobs/{job_id}/restore to restore a job and continue from where you left off"
    }


@app.post("/api/jobs/{job_id}/restore")
async def restore_job(job_id: str):
    """
    Restore a job from disk cache into memory.
    This allows continuing from where you left off after server restart.

    After restoring:
    - If has_markdown: Can call GET /api/markdown/{job_id} or POST /api/plan/{job_id}
    - If has_plan: Can call GET /api/plan/{job_id} or POST /api/manim/{job_id}
    - If has_manim: Can call GET /api/manim/{job_id}
    """
    output_dir = settings.OUTPUTS_DIR / job_id

    if not output_dir.exists():
        raise HTTPException(status_code=404, detail=f"No cached data found for job {job_id}")

    # Determine the current step based on what files exist
    has_markdown = (output_dir / "paper.md").exists()
    has_plan = (output_dir / "plan.json").exists()
    has_manim = (output_dir / "slides" / "manifest.json").exists()

    if has_manim:
        step = "manim_complete"
    elif has_plan:
        step = "plan_complete"
    elif has_markdown:
        step = "ocr_complete"
    else:
        step = "uploaded"

    # Restore job to in-memory storage
    jobs[job_id] = JobStatus(
        job_id=job_id,
        status="processing" if step != "manim_complete" else "complete",
        step=step
    )

    logger.info(f"Restored job {job_id} from disk cache at step: {step}")

    # Build next steps guidance
    next_steps = []
    if has_markdown and not has_plan:
        next_steps.append("POST /api/plan/{job_id} - Generate presentation plan")
    if has_plan and not has_manim:
        next_steps.append("POST /api/manim/{job_id} - Generate Manim code")
    if has_manim:
        next_steps.append("GET /api/manim/{job_id} - View generated code")

    return {
        "job_id": job_id,
        "restored_step": step,
        "has_markdown": has_markdown,
        "has_plan": has_plan,
        "has_manim": has_manim,
        "next_steps": next_steps,
        "message": f"Job restored successfully. You can continue from the '{step}' stage."
    }


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
    # Check if markdown exists (don't rely on in-memory job storage)
    markdown_path = settings.OUTPUTS_DIR / job_id / "paper.md"
    if not markdown_path.exists():
        raise HTTPException(status_code=404, detail="Markdown not found. Please upload and process a PDF first.")

    logger.info(f"Creating presentation plan for job: {job_id}")

    # Create job entry if it doesn't exist (server may have restarted)
    if job_id not in jobs:
        jobs[job_id] = JobStatus(job_id=job_id, status="processing", step="planning")
    else:
        jobs[job_id].step = "planning"

    try:
        markdown_content = markdown_path.read_text()
        logger.info(f"Read markdown content: {len(markdown_content)} chars")

        plan = await planning_service.create_presentation_plan(markdown_content)
        logger.info(f"Plan generated with {len(plan.slides)} slides")

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
        import traceback
        logger.error(traceback.format_exc())
        if job_id in jobs:
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


@app.post("/api/manim/{job_id}")
async def generate_manim_code(job_id: str):
    """
    Generate Manim code for all slides in the presentation plan.
    Generates code one slide at a time and saves to files.
    """
    # Check if plan exists
    plan_path = settings.OUTPUTS_DIR / job_id / "plan.json"
    if not plan_path.exists():
        raise HTTPException(status_code=404, detail="Plan not found. Create a plan first.")

    logger.info(f"Starting Manim code generation for job: {job_id}")

    # Create job entry if it doesn't exist
    if job_id not in jobs:
        jobs[job_id] = JobStatus(job_id=job_id, status="processing", step="manim_generation")
    else:
        jobs[job_id].step = "manim_generation"

    try:
        # Load the plan
        plan_data = json.loads(plan_path.read_text())
        plan = PresentationPlan(**plan_data)
        logger.info(f"Loaded plan with {len(plan.slides)} slides")

        # Create slides directory
        slides_dir = settings.OUTPUTS_DIR / job_id / "slides"
        slides_dir.mkdir(parents=True, exist_ok=True)

        # Generate code for each slide
        generated_slides = []
        for slide in plan.slides:
            slide_id = f"s{slide.slide_number:03d}"
            logger.info(f"Generating code for slide {slide_id}...")

            manim_slide = await manim_service.generate_slide_code(
                slide=slide,
                paper_title=plan.paper_title,
                paper_summary=plan.paper_summary
            )

            # Save the code to file
            code_path = slides_dir / f"{slide_id}.py"
            code_path.write_text(manim_slide.manim_code)
            logger.info(f"Saved Manim code to: {code_path}")

            generated_slides.append({
                "slide_id": slide_id,
                "slide_number": slide.slide_number,
                "title": slide.title,
                "class_name": manim_slide.class_name,
                "code_path": str(code_path),
                "expected_duration": manim_slide.expected_duration
            })

        # Save manifest of all generated slides
        manifest_path = slides_dir / "manifest.json"
        manifest_path.write_text(json.dumps(generated_slides, indent=2))
        logger.info(f"Saved manifest to: {manifest_path}")

        jobs[job_id].step = "manim_complete"

        return {
            "job_id": job_id,
            "status": "manim_complete",
            "slides_generated": len(generated_slides),
            "slides": generated_slides
        }

    except Exception as e:
        logger.error(f"Manim generation failed for job {job_id}: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        if job_id in jobs:
            jobs[job_id].status = "failed"
            jobs[job_id].error = str(e)
        raise HTTPException(status_code=500, detail=f"Manim generation failed: {str(e)}")


@app.get("/api/manim/{job_id}")
async def get_manim_code(job_id: str):
    """
    Get all generated Manim code for a job.
    """
    slides_dir = settings.OUTPUTS_DIR / job_id / "slides"
    manifest_path = slides_dir / "manifest.json"

    if not manifest_path.exists():
        raise HTTPException(status_code=404, detail="Manim code not found. Generate it first.")

    manifest = json.loads(manifest_path.read_text())

    # Load all code files
    slides_with_code = []
    for slide_info in manifest:
        code_path = Path(slide_info["code_path"])
        if code_path.exists():
            slide_info["code"] = code_path.read_text()
        slides_with_code.append(slide_info)

    return {"job_id": job_id, "slides": slides_with_code}


@app.get("/api/manim/{job_id}/{slide_id}")
async def get_slide_code(job_id: str, slide_id: str):
    """
    Get Manim code for a specific slide.
    slide_id should be like 's001', 's002', etc.
    """
    code_path = settings.OUTPUTS_DIR / job_id / "slides" / f"{slide_id}.py"

    if not code_path.exists():
        raise HTTPException(status_code=404, detail=f"Slide code not found: {slide_id}")

    return {
        "job_id": job_id,
        "slide_id": slide_id,
        "code": code_path.read_text()
    }


# ============================================
# DEVELOPMENT / TESTING ENDPOINTS
# These help test the frontend without API calls
# ============================================

@app.post("/api/dev/create-fixture")
async def create_dev_fixture():
    """
    Create a sample fixture job for development/testing.
    This creates pre-populated data so you can test the frontend
    without making actual API calls.

    The fixture includes:
    - Sample markdown (paper.md)
    - Sample plan (plan.json)
    - Sample Manim code (slides/s001.py, s002.py, s003.py)
    """
    job_id = "dev-test"

    # Create directories
    output_dir = settings.OUTPUTS_DIR / job_id
    output_dir.mkdir(parents=True, exist_ok=True)
    slides_dir = output_dir / "slides"
    slides_dir.mkdir(parents=True, exist_ok=True)

    # Sample markdown
    sample_markdown = """# Attention Is All You Need

## Abstract

The dominant sequence transduction models are based on complex recurrent or
convolutional neural networks that include an encoder and a decoder. The best
performing models also connect the encoder and decoder through an attention
mechanism. We propose a new simple network architecture, the Transformer,
based solely on attention mechanisms, dispensing with recurrence and convolutions
entirely.

## 1 Introduction

Recurrent neural networks, long short-term memory and gated recurrent neural
networks in particular, have been firmly established as state of the art approaches
in sequence modeling and transduction problems such as language modeling and
machine translation.

The Transformer allows for significantly more parallelization and can reach a new
state of the art in translation quality after being trained for as little as twelve hours
on eight P100 GPUs.

## 2 Model Architecture

The Transformer follows an encoder-decoder structure using stacked self-attention
and point-wise, fully connected layers for both the encoder and decoder.

### 2.1 Encoder and Decoder Stacks

**Encoder**: The encoder is composed of a stack of N = 6 identical layers.

**Decoder**: The decoder is also composed of a stack of N = 6 identical layers.

### 2.2 Attention

An attention function can be described as mapping a query and a set of key-value
pairs to an output, where the query, keys, values, and output are all vectors.

Scaled Dot-Product Attention:
Attention(Q, K, V) = softmax(QK^T / sqrt(d_k)) V

## 3 Results

On the WMT 2014 English-to-German translation task, the big transformer model
outperforms the best previously reported models including ensembles by more than
2.0 BLEU, establishing a new state-of-the-art BLEU score of 28.4.
"""

    # Sample plan
    sample_plan = {
        "paper_title": "The Transformer: Attention Is All You Need",
        "paper_summary": "Imagine you're trying to translate a sentence. Instead of reading word by word like a robot, you look at the whole sentence at once and figure out which words are most important to each other. That's what the Transformer does - it pays 'attention' to all parts of the input simultaneously, making it much faster and better at understanding language.",
        "target_duration_minutes": 5,
        "slides": [
            {
                "slide_number": 1,
                "title": "The Translation Challenge",
                "visual_type": "diagram",
                "visual_description": "A horizontal flow showing two thought bubbles: on the left, an English sentence 'The cat sat on the mat' with words highlighted in blue; on the right, the German translation 'Die Katze saß auf der Matte' with corresponding words highlighted in yellow. Animated arrows flow between related words, showing how 'cat' connects to 'Katze' and 'mat' connects to 'Matte'. The arrows pulse and glow to show the connection strength.",
                "key_points": [
                    "Translation requires understanding relationships between words",
                    "Some words in one language map to different positions in another",
                    "The challenge: how do we teach a computer to see these connections?"
                ],
                "voiceover_script": "Have you ever tried to translate something from one language to another? It's not just about swapping words one by one. The word order changes, some words don't have direct translations, and the meaning of one word often depends on other words around it. For decades, computers struggled with this. They would read sentences word by word, like following a recipe step by step. But what if there was a better way? What if a computer could look at the whole sentence at once, just like you do?",
                "duration_seconds": 45,
                "transition_note": "From the challenge, we move to how older models tried to solve it"
            },
            {
                "slide_number": 2,
                "title": "The Old Way: Sequential Processing",
                "visual_type": "diagram",
                "visual_description": "A horizontal chain of boxes representing an RNN, with each box processing one word. The first box takes 'The', passes information to the second box which takes 'cat', and so on. Show a dim memory signal that fades as it travels through the chain. Animate the signal getting weaker with each step, represented by decreasing opacity.",
                "key_points": [
                    "RNNs process words one at a time in sequence",
                    "Information must travel through each step",
                    "Long sentences cause the 'forgetting problem'"
                ],
                "voiceover_script": "Before the Transformer, we used something called Recurrent Neural Networks, or RNNs. Think of it like a game of telephone. The first person hears a message and whispers it to the next person, who whispers to the next, and so on. By the time it reaches the end, the message might be garbled. RNNs work similarly - they pass information from one word to the next. But here's the problem: if the sentence is long, the information about the first words gets weaker and weaker. It's like trying to remember what you had for breakfast last Tuesday.",
                "duration_seconds": 50,
                "transition_note": "Now introduce the key insight of attention"
            },
            {
                "slide_number": 3,
                "title": "The Key Insight: Attention",
                "visual_type": "equation",
                "visual_description": "Center the attention equation: Attention(Q, K, V) = softmax(QK^T / √d_k) V. Animate each component appearing one by one. Q appears as a blue vector labeled 'Query: What am I looking for?', K appears as a green vector labeled 'Keys: What's available?', V appears as a yellow vector labeled 'Values: What's the actual content?'. Show the dot product as vectors aligning, the softmax as a probability distribution bar chart, and the final multiplication as weighted averaging.",
                "key_points": [
                    "Query (Q): What information am I looking for?",
                    "Key (K): What information is available?",
                    "Value (V): What is the actual content?",
                    "Attention scores tell us how much to focus on each part"
                ],
                "voiceover_script": "Here's where it gets exciting. The Transformer introduces something called 'attention'. Imagine you're in a crowded room trying to find your friend. Your eyes don't look at every single person equally - they scan quickly and focus on people who look like your friend. That's attention. In math terms, we have three things: a Query - what you're looking for; Keys - labels on everything available; and Values - the actual information. When the Query matches a Key well, we pay more attention to that Value. The formula looks scary, but it's just asking 'how similar is what I'm looking for to what's available?' and then focusing on the most similar things.",
                "duration_seconds": 60,
                "transition_note": "From the concept to the full architecture"
            }
        ]
    }

    # Sample Manim code for slides
    sample_manim_code = {
        "s001": '''from manim import *

class Slide001(Scene):
    def construct(self):
        # Title
        title = Text("The Translation Challenge", font_size=48)
        title.to_edge(UP)
        self.play(Write(title))
        self.wait(0.5)

        # English sentence
        english = Text("The cat sat on the mat", font_size=32, color=BLUE)
        english.shift(UP * 1 + LEFT * 3)

        # German sentence
        german = Text("Die Katze saß auf der Matte", font_size=32, color=YELLOW)
        german.shift(DOWN * 1 + RIGHT * 2)

        self.play(Write(english))
        self.wait(0.5)
        self.play(Write(german))
        self.wait(0.5)

        # Connection arrows
        arrow1 = Arrow(english.get_bottom(), german.get_top(), color=GREEN)
        self.play(Create(arrow1))
        self.wait(1)

        # Conclusion text
        conclusion = Text("How do we teach computers\\nto see these connections?",
                         font_size=28, color=WHITE)
        conclusion.to_edge(DOWN)
        self.play(FadeIn(conclusion))
        self.wait(2)
''',
        "s002": '''from manim import *

class Slide002(Scene):
    def construct(self):
        # Title
        title = Text("The Old Way: Sequential Processing", font_size=42)
        title.to_edge(UP)
        self.play(Write(title))
        self.wait(0.5)

        # RNN boxes
        words = ["The", "cat", "sat", "on", "the", "mat"]
        boxes = VGroup()
        for i, word in enumerate(words):
            box = VGroup(
                Square(side_length=1, color=BLUE),
                Text(word, font_size=20)
            )
            box.shift(RIGHT * (i * 1.5 - 3.5))
            boxes.add(box)

        self.play(Create(boxes))
        self.wait(0.5)

        # Arrows between boxes showing information flow
        arrows = VGroup()
        for i in range(len(words) - 1):
            arrow = Arrow(
                boxes[i].get_right(),
                boxes[i + 1].get_left(),
                color=YELLOW,
                buff=0.1
            )
            arrows.add(arrow)

        self.play(Create(arrows))
        self.wait(0.5)

        # Fading signal
        signal = Dot(color=RED, radius=0.2)
        signal.move_to(boxes[0].get_center())
        self.play(FadeIn(signal))

        for i in range(len(words) - 1):
            self.play(
                signal.animate.move_to(boxes[i + 1].get_center()),
                signal.animate.set_opacity(1 - (i + 1) * 0.15),
                run_time=0.5
            )

        # Problem text
        problem = Text("Information fades over long sequences!", font_size=28, color=RED)
        problem.to_edge(DOWN)
        self.play(Write(problem))
        self.wait(2)
''',
        "s003": '''from manim import *

class Slide003(Scene):
    def construct(self):
        # Title
        title = Text("The Key Insight: Attention", font_size=42)
        title.to_edge(UP)
        self.play(Write(title))
        self.wait(0.5)

        # Attention equation
        equation = MathTex(
            r"\\text{Attention}(Q, K, V) = \\text{softmax}\\left(\\frac{QK^T}{\\sqrt{d_k}}\\right) V",
            font_size=36
        )
        self.play(Write(equation))
        self.wait(1)

        # Move equation up
        self.play(equation.animate.shift(UP * 1.5))

        # Q, K, V explanations
        q_text = Text("Q = Query: What am I looking for?", font_size=24, color=BLUE)
        k_text = Text("K = Key: What's available?", font_size=24, color=GREEN)
        v_text = Text("V = Value: What's the content?", font_size=24, color=YELLOW)

        explanations = VGroup(q_text, k_text, v_text)
        explanations.arrange(DOWN, buff=0.3)
        explanations.shift(DOWN * 1)

        for exp in explanations:
            self.play(FadeIn(exp, shift=RIGHT))
            self.wait(0.5)

        self.wait(2)
'''
    }

    # Write files
    (output_dir / "paper.md").write_text(sample_markdown)
    (output_dir / "plan.json").write_text(json.dumps(sample_plan, indent=2))

    manifest = []
    for slide_id, code in sample_manim_code.items():
        code_path = slides_dir / f"{slide_id}.py"
        code_path.write_text(code)
        slide_num = int(slide_id[1:])
        manifest.append({
            "slide_id": slide_id,
            "slide_number": slide_num,
            "title": sample_plan["slides"][slide_num - 1]["title"],
            "class_name": f"Slide{slide_num:03d}",
            "code_path": str(code_path),
            "expected_duration": sample_plan["slides"][slide_num - 1]["duration_seconds"]
        })

    (slides_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))

    # Restore job to memory
    jobs[job_id] = JobStatus(
        job_id=job_id,
        status="complete",
        step="manim_complete"
    )

    logger.info(f"Created dev fixture: {job_id}")

    return {
        "job_id": job_id,
        "message": "Development fixture created successfully",
        "files_created": [
            f"outputs/{job_id}/paper.md",
            f"outputs/{job_id}/plan.json",
            f"outputs/{job_id}/slides/s001.py",
            f"outputs/{job_id}/slides/s002.py",
            f"outputs/{job_id}/slides/s003.py",
            f"outputs/{job_id}/slides/manifest.json"
        ],
        "usage": {
            "view_markdown": f"GET /api/markdown/{job_id}",
            "view_plan": f"GET /api/plan/{job_id}",
            "view_manim": f"GET /api/manim/{job_id}"
        }
    }


# ============================================
# RENDERING ENDPOINTS (Generative Manim API)
# These actually render Manim code into videos
# ============================================

@app.get("/api/render/status")
async def render_status():
    """
    Check if the Generative Manim render API is available.

    The render API must be running separately:
    - Local: docker run -p 8080:8080 generative-manim-api
    - Or use a hosted instance

    Returns availability status and configuration.
    """
    is_available = await render_service.check_availability()

    return {
        "render_enabled": settings.RENDER_ENABLED,
        "api_url": settings.GENERATIVE_MANIM_API_URL,
        "api_available": is_available,
        "message": "Render API is ready" if is_available else "Render API not available. Run the Generative Manim API first."
    }


@app.post("/api/render/{job_id}/{slide_id}")
async def render_slide(job_id: str, slide_id: str):
    """
    Render a single slide to video using the Generative Manim API.

    This actually runs the Manim code and produces a video file,
    catching runtime errors that static validation would miss.

    Args:
        job_id: The job ID
        slide_id: The slide ID (e.g., 's001', 's002')

    Returns:
        Render result with video URL or error message
    """
    # Check if render API is available
    if not await render_service.check_availability():
        raise HTTPException(
            status_code=503,
            detail="Render API not available. Start the Generative Manim API first."
        )

    # Get the slide code
    code_path = settings.OUTPUTS_DIR / job_id / "slides" / f"{slide_id}.py"
    if not code_path.exists():
        raise HTTPException(status_code=404, detail=f"Slide code not found: {slide_id}")

    # Load manifest to get class name
    manifest_path = settings.OUTPUTS_DIR / job_id / "slides" / "manifest.json"
    if not manifest_path.exists():
        raise HTTPException(status_code=404, detail="Manifest not found")

    manifest = json.loads(manifest_path.read_text())
    slide_info = next((s for s in manifest if s["slide_id"] == slide_id), None)
    if not slide_info:
        raise HTTPException(status_code=404, detail=f"Slide not in manifest: {slide_id}")

    code = code_path.read_text()
    class_name = slide_info["class_name"]

    logger.info(f"Rendering slide {slide_id} (class: {class_name}) for job {job_id}")

    result = await render_service.render_code(code, class_name)

    if result.success:
        return {
            "job_id": job_id,
            "slide_id": slide_id,
            "status": "success",
            "video_url": result.video_url,
            "video_path": result.video_path,
            "render_time": result.render_time
        }
    else:
        return {
            "job_id": job_id,
            "slide_id": slide_id,
            "status": "failed",
            "error": result.error_message
        }


@app.post("/api/render/{job_id}")
async def render_all_slides(job_id: str):
    """
    Render all slides for a job to videos.

    This processes each slide sequentially and returns results.
    Failed slides include error messages that can be used for auto-fixing.

    Args:
        job_id: The job ID

    Returns:
        List of render results for each slide
    """
    # Check if render API is available
    if not await render_service.check_availability():
        raise HTTPException(
            status_code=503,
            detail="Render API not available. Start the Generative Manim API first."
        )

    # Load manifest
    manifest_path = settings.OUTPUTS_DIR / job_id / "slides" / "manifest.json"
    if not manifest_path.exists():
        raise HTTPException(status_code=404, detail="Manifest not found. Generate Manim code first.")

    manifest = json.loads(manifest_path.read_text())
    slides_dir = settings.OUTPUTS_DIR / job_id / "slides"

    logger.info(f"Starting render of {len(manifest)} slides for job {job_id}")

    results = []
    successful = 0
    failed = 0

    for slide_info in manifest:
        code_path = Path(slide_info["code_path"])
        slide_id = slide_info["slide_id"]
        class_name = slide_info["class_name"]

        if not code_path.exists():
            results.append({
                "slide_id": slide_id,
                "status": "failed",
                "error": f"Code file not found: {code_path}"
            })
            failed += 1
            continue

        code = code_path.read_text()
        result = await render_service.render_code(code, class_name)

        if result.success:
            results.append({
                "slide_id": slide_id,
                "status": "success",
                "video_url": result.video_url,
                "video_path": result.video_path,
                "render_time": result.render_time
            })
            successful += 1
        else:
            results.append({
                "slide_id": slide_id,
                "status": "failed",
                "error": result.error_message
            })
            failed += 1

    logger.info(f"Render complete: {successful} successful, {failed} failed")

    return {
        "job_id": job_id,
        "total_slides": len(manifest),
        "successful": successful,
        "failed": failed,
        "results": results
    }


@app.post("/api/render/{job_id}/{slide_id}/fix")
async def render_and_fix_slide(job_id: str, slide_id: str, max_attempts: int = 3):
    """
    Render a slide and auto-fix if it fails.

    This is the full validation loop:
    1. Attempt to render the slide
    2. If it fails, send the error to Claude for fixing
    3. Repeat up to max_attempts times

    Args:
        job_id: The job ID
        slide_id: The slide ID
        max_attempts: Maximum fix attempts (default 3)

    Returns:
        Final render result, with fix history if applicable
    """
    # Check if render API is available
    if not await render_service.check_availability():
        raise HTTPException(
            status_code=503,
            detail="Render API not available. Start the Generative Manim API first."
        )

    # Get the slide code and info
    code_path = settings.OUTPUTS_DIR / job_id / "slides" / f"{slide_id}.py"
    if not code_path.exists():
        raise HTTPException(status_code=404, detail=f"Slide code not found: {slide_id}")

    manifest_path = settings.OUTPUTS_DIR / job_id / "slides" / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    slide_info = next((s for s in manifest if s["slide_id"] == slide_id), None)
    if not slide_info:
        raise HTTPException(status_code=404, detail=f"Slide not in manifest: {slide_id}")

    code = code_path.read_text()
    class_name = slide_info["class_name"]
    fix_history = []

    for attempt in range(max_attempts + 1):
        logger.info(f"Render attempt {attempt + 1}/{max_attempts + 1} for {slide_id}")

        result = await render_service.render_code(code, class_name)

        if result.success:
            # Success! Save the fixed code if we made changes
            if attempt > 0:
                code_path.write_text(code)
                logger.info(f"Saved fixed code for {slide_id}")

            return {
                "job_id": job_id,
                "slide_id": slide_id,
                "status": "success",
                "video_url": result.video_url,
                "attempts": attempt + 1,
                "fix_history": fix_history
            }

        # Render failed - try to fix
        fix_history.append({
            "attempt": attempt + 1,
            "error": result.error_message
        })

        if attempt >= max_attempts:
            # Exhausted attempts
            return {
                "job_id": job_id,
                "slide_id": slide_id,
                "status": "failed",
                "error": result.error_message,
                "attempts": attempt + 1,
                "fix_history": fix_history,
                "message": f"Failed to fix after {max_attempts} attempts"
            }

        # Request fix from Claude
        logger.info(f"Requesting fix from Claude for {slide_id}...")
        code = manim_service._request_fix(
            code,
            [f"[RENDER_ERROR] {result.error_message}"],
            class_name
        )

    # Should not reach here
    return {
        "job_id": job_id,
        "slide_id": slide_id,
        "status": "failed",
        "message": "Unexpected error in fix loop"
    }


# ============================================
# DIRECT VIDEO GENERATION ENDPOINTS
# These use GM API to generate code + render in one step
# ============================================

@app.post("/api/generate/{job_id}/{slide_number}")
async def generate_video_from_plan(job_id: str, slide_number: int, engine: str = "anthropic"):
    """
    Generate a video directly from a slide's visual description.

    This is the streamlined workflow:
    1. Load the slide's visual_description from the plan
    2. Send it to GM API's code generation endpoint
    3. Render the generated code to video

    No manual code generation - the GM API handles everything using
    their fine-tuned Manim prompts.

    Args:
        job_id: The job ID
        slide_number: The slide number (1-indexed)
        engine: LLM engine to use ("anthropic" or "openai")

    Returns:
        Video URL and generated code
    """
    # Check if render API is available
    if not await render_service.check_availability():
        raise HTTPException(
            status_code=503,
            detail="Generative Manim API not available. Start it first."
        )

    # Load the plan
    plan_path = settings.OUTPUTS_DIR / job_id / "plan.json"
    if not plan_path.exists():
        raise HTTPException(status_code=404, detail="Plan not found. Create a plan first.")

    plan_data = json.loads(plan_path.read_text())

    # Find the slide
    slides = plan_data.get("slides", [])
    slide = next((s for s in slides if s["slide_number"] == slide_number), None)
    if not slide:
        raise HTTPException(status_code=404, detail=f"Slide {slide_number} not found in plan")

    # Build a rich prompt from the slide's visual description
    visual_desc = slide.get("visual_description", "")
    title = slide.get("title", f"Slide {slide_number}")
    key_points = slide.get("key_points", [])

    prompt = f"""Create a Manim animation for a presentation slide titled "{title}".

Visual Description:
{visual_desc}

Key Points to Visualize:
{chr(10).join(f"- {point}" for point in key_points)}

Requirements:
- Create a clear, educational animation
- Use appropriate colors and layout
- Include smooth transitions between elements
- The animation should be self-explanatory
"""

    logger.info(f"Generating video for slide {slide_number} via GM API (engine: {engine})")
    logger.debug(f"Prompt: {prompt[:500]}...")

    # Use GM API to generate AND render in one step
    result = await render_service.generate_and_render(
        prompt=prompt,
        class_name=f"Slide{slide_number:03d}",
        engine=engine
    )

    if result.success:
        # Save the generated code for reference
        slides_dir = settings.OUTPUTS_DIR / job_id / "slides"
        slides_dir.mkdir(parents=True, exist_ok=True)

        slide_id = f"s{slide_number:03d}"
        code_path = slides_dir / f"{slide_id}_gm.py"  # _gm suffix = generated by GM API
        if result.code:
            code_path.write_text(result.code)
            logger.info(f"Saved GM-generated code to: {code_path}")

        return {
            "job_id": job_id,
            "slide_number": slide_number,
            "status": "success",
            "video_url": result.video_url,
            "video_path": result.video_path,
            "render_time": result.render_time,
            "code": result.code,
            "code_saved_to": str(code_path),
            "engine_used": engine
        }
    else:
        return {
            "job_id": job_id,
            "slide_number": slide_number,
            "status": "failed",
            "error": result.error_message,
            "engine_used": engine
        }


@app.post("/api/generate/{job_id}")
async def generate_all_videos_from_plan(job_id: str, engine: str = "anthropic"):
    """
    Generate videos for all slides directly from visual descriptions.

    This processes the entire plan, using the GM API to:
    1. Generate Manim code from each slide's visual_description
    2. Render each slide to video

    This is the fastest way to go from plan to videos.

    Args:
        job_id: The job ID
        engine: LLM engine to use ("anthropic" or "openai")

    Returns:
        Results for all slides
    """
    # Check if render API is available
    if not await render_service.check_availability():
        raise HTTPException(
            status_code=503,
            detail="Generative Manim API not available. Start it first."
        )

    # Load the plan
    plan_path = settings.OUTPUTS_DIR / job_id / "plan.json"
    if not plan_path.exists():
        raise HTTPException(status_code=404, detail="Plan not found. Create a plan first.")

    plan_data = json.loads(plan_path.read_text())
    slides = plan_data.get("slides", [])

    if not slides:
        raise HTTPException(status_code=400, detail="Plan has no slides")

    logger.info(f"Generating {len(slides)} videos via GM API for job {job_id}")

    # Create slides directory
    slides_dir = settings.OUTPUTS_DIR / job_id / "slides"
    slides_dir.mkdir(parents=True, exist_ok=True)

    results = []
    successful = 0
    failed = 0
    gm_manifest = []

    for slide in slides:
        slide_number = slide["slide_number"]
        visual_desc = slide.get("visual_description", "")
        title = slide.get("title", f"Slide {slide_number}")
        key_points = slide.get("key_points", [])

        # Build prompt
        prompt = f"""Create a Manim animation for a presentation slide titled "{title}".

Visual Description:
{visual_desc}

Key Points to Visualize:
{chr(10).join(f"- {point}" for point in key_points)}

Requirements:
- Create a clear, educational animation
- Use appropriate colors and layout
- Include smooth transitions between elements
"""

        logger.info(f"Generating slide {slide_number}/{len(slides)}...")

        result = await render_service.generate_and_render(
            prompt=prompt,
            class_name=f"Slide{slide_number:03d}",
            engine=engine
        )

        slide_id = f"s{slide_number:03d}"

        if result.success:
            # Save generated code
            code_path = slides_dir / f"{slide_id}_gm.py"
            if result.code:
                code_path.write_text(result.code)

            results.append({
                "slide_number": slide_number,
                "slide_id": slide_id,
                "title": title,
                "status": "success",
                "video_url": result.video_url,
                "render_time": result.render_time
            })
            successful += 1

            # Add to manifest
            gm_manifest.append({
                "slide_id": slide_id,
                "slide_number": slide_number,
                "title": title,
                "class_name": f"Slide{slide_number:03d}",
                "code_path": str(code_path),
                "video_url": result.video_url,
                "video_path": result.video_path,
                "source": "generative_manim_api"
            })
        else:
            results.append({
                "slide_number": slide_number,
                "slide_id": slide_id,
                "title": title,
                "status": "failed",
                "error": result.error_message
            })
            failed += 1

    # Save GM manifest (separate from manual code manifest)
    gm_manifest_path = slides_dir / "gm_manifest.json"
    gm_manifest_path.write_text(json.dumps(gm_manifest, indent=2))
    logger.info(f"Saved GM manifest to: {gm_manifest_path}")

    return {
        "job_id": job_id,
        "engine": engine,
        "total_slides": len(slides),
        "successful": successful,
        "failed": failed,
        "results": results,
        "manifest_path": str(gm_manifest_path)
    }


@app.post("/api/generate/custom")
async def generate_custom_video(prompt: str, engine: str = "anthropic"):
    """
    Generate a video from a custom prompt.

    This is useful for testing the GM API or creating one-off animations
    without going through the full pipeline.

    Args:
        prompt: Text description of the animation to create
        engine: LLM engine to use ("anthropic" or "openai")

    Returns:
        Video URL and generated code
    """
    # Check if render API is available
    if not await render_service.check_availability():
        raise HTTPException(
            status_code=503,
            detail="Generative Manim API not available. Start it first."
        )

    logger.info(f"Generating custom video via GM API (engine: {engine})")

    result = await render_service.generate_and_render(
        prompt=prompt,
        class_name="CustomScene",
        engine=engine
    )

    if result.success:
        return {
            "status": "success",
            "video_url": result.video_url,
            "video_path": result.video_path,
            "render_time": result.render_time,
            "code": result.code,
            "engine_used": engine
        }
    else:
        return {
            "status": "failed",
            "error": result.error_message,
            "engine_used": engine
        }


# ============================================
# BACKGROUND VIDEO GENERATION (Non-blocking)
# Use these for long-running generation tasks
# ============================================

async def _generate_videos_background(job_id: str, engine: str):
    """Background task to generate all videos for a job."""
    task = generation_tasks[job_id]

    try:
        # Load the plan
        plan_path = settings.OUTPUTS_DIR / job_id / "plan.json"
        plan_data = json.loads(plan_path.read_text())
        slides = plan_data.get("slides", [])

        task["total_slides"] = len(slides)

        # Create slides directory
        slides_dir = settings.OUTPUTS_DIR / job_id / "slides"
        slides_dir.mkdir(parents=True, exist_ok=True)

        gm_manifest = []

        for i, slide in enumerate(slides):
            # Check for cancellation
            if task.get("cancel_flag"):
                task["status"] = "cancelled"
                logger.info(f"Generation cancelled for job {job_id}")
                return

            slide_number = slide["slide_number"]
            visual_desc = slide.get("visual_description", "")
            title = slide.get("title", f"Slide {slide_number}")
            key_points = slide.get("key_points", [])

            task["current_slide"] = slide_number
            task["current_title"] = title

            # Build prompt
            prompt = f"""Create a Manim animation for a presentation slide titled "{title}".

Visual Description:
{visual_desc}

Key Points to Visualize:
{chr(10).join(f"- {point}" for point in key_points)}

Requirements:
- Create a clear, educational animation
- Use appropriate colors and layout
- Include smooth transitions between elements
"""

            logger.info(f"[BG] Generating slide {slide_number}/{len(slides)} for job {job_id}...")

            result = await render_service.generate_and_render(
                prompt=prompt,
                class_name=f"Slide{slide_number:03d}",
                engine=engine
            )

            slide_id = f"s{slide_number:03d}"

            if result.success:
                # Save generated code
                code_path = slides_dir / f"{slide_id}_gm.py"
                if result.code:
                    code_path.write_text(result.code)

                slide_result = {
                    "slide_number": slide_number,
                    "slide_id": slide_id,
                    "title": title,
                    "status": "success",
                    "video_url": result.video_url,
                    "render_time": result.render_time
                }
                task["successful"] += 1

                gm_manifest.append({
                    "slide_id": slide_id,
                    "slide_number": slide_number,
                    "title": title,
                    "class_name": f"Slide{slide_number:03d}",
                    "code_path": str(code_path),
                    "video_url": result.video_url,
                    "video_path": result.video_path,
                    "source": "generative_manim_api"
                })
            else:
                slide_result = {
                    "slide_number": slide_number,
                    "slide_id": slide_id,
                    "title": title,
                    "status": "failed",
                    "error": result.error_message
                }
                task["failed"] += 1

            task["results"].append(slide_result)
            task["completed_slides"] = i + 1

        # Save GM manifest
        gm_manifest_path = slides_dir / "gm_manifest.json"
        gm_manifest_path.write_text(json.dumps(gm_manifest, indent=2))

        task["status"] = "complete"
        task["manifest_path"] = str(gm_manifest_path)
        logger.info(f"[BG] Generation complete for job {job_id}: {task['successful']} success, {task['failed']} failed")

    except Exception as e:
        task["status"] = "error"
        task["error"] = str(e)
        logger.error(f"[BG] Generation error for job {job_id}: {e}")


@app.post("/api/generate/{job_id}/start")
async def start_video_generation(job_id: str, background_tasks: BackgroundTasks, engine: str = "anthropic"):
    """
    Start video generation in the background.

    This returns immediately and processes slides in the background.
    Use /api/generate/{job_id}/progress to check status.
    Use /api/generate/{job_id}/cancel to stop generation.

    Args:
        job_id: The job ID
        engine: LLM engine to use ("anthropic" or "openai")

    Returns:
        Task ID and status URL
    """
    # Check if already running
    if job_id in generation_tasks and generation_tasks[job_id]["status"] == "running":
        return {
            "job_id": job_id,
            "status": "already_running",
            "message": "Generation already in progress. Check /api/generate/{job_id}/progress"
        }

    # Check if render API is available
    if not await render_service.check_availability():
        raise HTTPException(
            status_code=503,
            detail="Generative Manim API not available. Start it first."
        )

    # Load the plan to validate
    plan_path = settings.OUTPUTS_DIR / job_id / "plan.json"
    if not plan_path.exists():
        raise HTTPException(status_code=404, detail="Plan not found. Create a plan first.")

    plan_data = json.loads(plan_path.read_text())
    slides = plan_data.get("slides", [])

    if not slides:
        raise HTTPException(status_code=400, detail="Plan has no slides")

    # Initialize task tracker
    generation_tasks[job_id] = {
        "status": "running",
        "engine": engine,
        "total_slides": len(slides),
        "completed_slides": 0,
        "current_slide": 0,
        "current_title": "",
        "successful": 0,
        "failed": 0,
        "results": [],
        "cancel_flag": False,
        "error": None
    }

    # Start background task
    background_tasks.add_task(_generate_videos_background, job_id, engine)

    logger.info(f"Started background generation for job {job_id} with {len(slides)} slides")

    return {
        "job_id": job_id,
        "status": "started",
        "total_slides": len(slides),
        "progress_url": f"/api/generate/{job_id}/progress",
        "cancel_url": f"/api/generate/{job_id}/cancel"
    }


@app.get("/api/generate/{job_id}/progress")
async def get_generation_progress(job_id: str):
    """
    Get the current progress of background video generation.

    Returns:
        Current status, progress percentage, and results so far
    """
    if job_id not in generation_tasks:
        raise HTTPException(status_code=404, detail="No generation task found. Start one first.")

    task = generation_tasks[job_id]

    progress_pct = 0
    if task["total_slides"] > 0:
        progress_pct = round(task["completed_slides"] / task["total_slides"] * 100, 1)

    return {
        "job_id": job_id,
        "status": task["status"],
        "progress_percent": progress_pct,
        "completed_slides": task["completed_slides"],
        "total_slides": task["total_slides"],
        "current_slide": task["current_slide"],
        "current_title": task["current_title"],
        "successful": task["successful"],
        "failed": task["failed"],
        "results": task["results"],
        "error": task.get("error")
    }


@app.post("/api/generate/{job_id}/cancel")
async def cancel_video_generation(job_id: str):
    """
    Cancel an in-progress video generation.

    The current slide will finish, but no new slides will start.

    Returns:
        Cancellation status
    """
    if job_id not in generation_tasks:
        raise HTTPException(status_code=404, detail="No generation task found.")

    task = generation_tasks[job_id]

    if task["status"] != "running":
        return {
            "job_id": job_id,
            "status": task["status"],
            "message": f"Task is not running (status: {task['status']})"
        }

    task["cancel_flag"] = True
    logger.info(f"Cancellation requested for job {job_id}")

    return {
        "job_id": job_id,
        "status": "cancelling",
        "message": "Cancellation requested. Current slide will finish, then generation will stop.",
        "completed_so_far": task["completed_slides"]
    }


# ============================================
# KODISC API VIDEO GENERATION
# Hosted solution - no self-hosting needed
# Cost: $0.025 per video (10 credits)
# ============================================

# Track Kodisc generation tasks separately
kodisc_tasks: dict[str, dict] = {}


@app.get("/api/kodisc/status")
async def kodisc_status():
    """
    Check if Kodisc API is configured and ready.
    """
    is_configured = kodisc_service.is_configured()

    return {
        "configured": is_configured,
        "message": "Kodisc API ready" if is_configured else "Add KODISC_API_KEY to .env",
        "cost_per_video": "$0.025 (10 credits)"
    }


async def _generate_kodisc_videos_background(job_id: str):
    """Background task to generate all videos for a job using Kodisc."""
    task = kodisc_tasks[job_id]

    try:
        # Load the plan
        plan_path = settings.OUTPUTS_DIR / job_id / "plan.json"
        plan_data = json.loads(plan_path.read_text())
        slides = plan_data.get("slides", [])

        task["total_slides"] = len(slides)

        # Create videos directory for this job
        videos_dir = settings.OUTPUTS_DIR / job_id / "videos"
        videos_dir.mkdir(parents=True, exist_ok=True)

        video_manifest = []

        for i, slide in enumerate(slides):
            # Check for cancellation
            if task.get("cancel_flag"):
                task["status"] = "cancelled"
                logger.info(f"Kodisc generation cancelled for job {job_id}")
                break

            slide_number = slide["slide_number"]
            visual_desc = slide.get("visual_description", "")
            title = slide.get("title", f"Slide {slide_number}")
            key_points = slide.get("key_points", [])

            task["current_slide"] = slide_number
            task["current_title"] = title

            # Build Kodisc-safe prompt with safety constraints to prevent crashes
            kodisc_prefix = (
                "Create a 3Blue1Brown-style Manim scene. BLACK background. "
                "SAFETY RULES (CRITICAL): "
                "1) MAX 30 objects - for 'many' items, use 5-10 and animate them. "
                "2) Use Text() for English, MathTex ONLY for actual equations. "
                "3) NO SVGMobject or ImageMobject - only Circle, Rectangle, Line, Arrow, Text. "
                "4) Each animation RunTime <= 2 seconds. "
                "5) For 'overload/many': draw 5 items moving fast, NOT 100 items. "
                "Use morph, flow, grow animations. "
            )

            # Primary prompt - use the visual description with safety prefix
            primary_prompt = kodisc_prefix + (visual_desc if visual_desc else f"Simple diagram for: {title}")

            # Middle-ground prompt - still animated but simpler (not just text)
            middle_prompt = (
                f"Create a Manim scene. BLACK background. MAX 20 objects. "
                f"Show title '{title[:25]}' at top using Write animation. "
                f"Below, draw a BLUE circle. Transform it into a YELLOW square. "
                f"This represents the concept of '{title[:20]}'."
            )

            # Guaranteed fallback - always renders
            fallback_prompt = (
                f"Create a simple Manim scene. BLACK background. "
                f"Center the text '{title[:25]}' in WHITE using Text(). "
                f"Use Write animation."
            )

            logger.info(f"[Kodisc] Generating slide {slide_number}/{len(slides)} for job {job_id}...")
            logger.info(f"[Kodisc] Primary prompt: {primary_prompt[:120]}...")

            # Try primary prompt first
            result = await kodisc_service.generate_video(
                prompt=primary_prompt,
                aspect_ratio="16:9",
                voiceover=False
            )

            attempt = 1
            used_prompt = "primary"

            # If primary fails, try middle-ground prompt (still has animation)
            if not result.success:
                logger.warning(f"[Kodisc] Primary prompt failed for slide {slide_number}, trying middle-ground...")
                result = await kodisc_service.generate_video(
                    prompt=middle_prompt,
                    aspect_ratio="16:9",
                    voiceover=False
                )
                attempt = 2
                used_prompt = "middle"

            # If middle also fails, try guaranteed fallback
            if not result.success:
                logger.warning(f"[Kodisc] Middle prompt failed for slide {slide_number}, trying fallback...")
                result = await kodisc_service.generate_video(
                    prompt=fallback_prompt,
                    aspect_ratio="16:9",
                    voiceover=False
                )
                attempt = 3
                used_prompt = "fallback"

            slide_id = f"s{slide_number:03d}"

            if result.success:
                # Save the generated code for reference
                if result.code:
                    code_path = videos_dir / f"{slide_id}_kodisc.py"
                    code_path.write_text(result.code)

                # Track if we used a fallback
                status = "success" if used_prompt == "primary" else f"success_via_{used_prompt}"
                logger.info(f"[Kodisc] Slide {slide_number} succeeded via {used_prompt} prompt (attempt {attempt})")

                slide_result = {
                    "slide_number": slide_number,
                    "slide_id": slide_id,
                    "title": title,
                    "status": "success",
                    "video_url": result.video_url,
                    "attempts": attempt,
                    "prompt_used": used_prompt
                }
                task["successful"] += 1

                video_manifest.append({
                    "slide_id": slide_id,
                    "slide_number": slide_number,
                    "title": title,
                    "video_url": result.video_url,
                    "code_path": str(videos_dir / f"{slide_id}_kodisc.py") if result.code else None,
                    "source": "kodisc",
                    "prompt_used": used_prompt
                })
            else:
                # All 3 attempts failed
                logger.error(f"[Kodisc] Slide {slide_number} failed after all 3 attempts")
                slide_result = {
                    "slide_number": slide_number,
                    "slide_id": slide_id,
                    "title": title,
                    "status": "failed",
                    "error": result.error,
                    "attempts": 3
                }
                task["failed"] += 1

            task["results"].append(slide_result)
            task["completed_slides"] = i + 1

        # Save video manifest (so user can revisit without regenerating)
        manifest_path = videos_dir / "kodisc_manifest.json"
        manifest_path.write_text(json.dumps(video_manifest, indent=2))

        # Also save the full task results
        results_path = videos_dir / "generation_results.json"
        results_path.write_text(json.dumps({
            "job_id": job_id,
            "total_slides": task["total_slides"],
            "successful": task["successful"],
            "failed": task["failed"],
            "results": task["results"]
        }, indent=2))

        task["status"] = "complete"
        task["manifest_path"] = str(manifest_path)
        logger.info(f"[Kodisc] Generation complete for job {job_id}: {task['successful']} success, {task['failed']} failed")

    except Exception as e:
        task["status"] = "error"
        task["error"] = str(e)
        logger.error(f"[Kodisc] Generation error for job {job_id}: {e}")


@app.post("/api/kodisc/{job_id}/start")
async def start_kodisc_generation(job_id: str, background_tasks: BackgroundTasks):
    """
    Start video generation using Kodisc API (background task).

    This uses the visual_description from each slide in the plan
    and sends it to Kodisc to generate Manim videos.

    Cost: ~$0.025 per slide (10 credits)

    Returns immediately - poll /api/kodisc/{job_id}/progress for status.
    """
    # Check if Kodisc is configured
    if not kodisc_service.is_configured():
        raise HTTPException(
            status_code=503,
            detail="Kodisc API key not configured. Add KODISC_API_KEY to .env"
        )

    # Check if already running
    if job_id in kodisc_tasks and kodisc_tasks[job_id]["status"] == "running":
        return {
            "job_id": job_id,
            "status": "already_running",
            "message": "Generation already in progress. Check /api/kodisc/{job_id}/progress"
        }

    # Load the plan to validate
    plan_path = settings.OUTPUTS_DIR / job_id / "plan.json"
    if not plan_path.exists():
        raise HTTPException(status_code=404, detail="Plan not found. Create a plan first.")

    plan_data = json.loads(plan_path.read_text())
    slides = plan_data.get("slides", [])

    if not slides:
        raise HTTPException(status_code=400, detail="Plan has no slides")

    # Estimate cost
    estimated_cost = len(slides) * 0.025

    # Initialize task tracker
    kodisc_tasks[job_id] = {
        "status": "running",
        "total_slides": len(slides),
        "completed_slides": 0,
        "current_slide": 0,
        "current_title": "",
        "successful": 0,
        "failed": 0,
        "results": [],
        "cancel_flag": False,
        "error": None
    }

    # Start background task
    background_tasks.add_task(_generate_kodisc_videos_background, job_id)

    logger.info(f"Started Kodisc generation for job {job_id} with {len(slides)} slides (~${estimated_cost:.2f})")

    return {
        "job_id": job_id,
        "status": "started",
        "total_slides": len(slides),
        "estimated_cost": f"${estimated_cost:.2f}",
        "progress_url": f"/api/kodisc/{job_id}/progress",
        "cancel_url": f"/api/kodisc/{job_id}/cancel"
    }


@app.get("/api/kodisc/{job_id}/progress")
async def get_kodisc_progress(job_id: str):
    """
    Get the current progress of Kodisc video generation.
    """
    if job_id not in kodisc_tasks:
        # Check if there's a saved result on disk
        results_path = settings.OUTPUTS_DIR / job_id / "videos" / "generation_results.json"
        if results_path.exists():
            saved_results = json.loads(results_path.read_text())
            return {
                "job_id": job_id,
                "status": "complete",
                "from_cache": True,
                **saved_results
            }
        raise HTTPException(status_code=404, detail="No Kodisc generation task found. Start one first.")

    task = kodisc_tasks[job_id]

    progress_pct = 0
    if task["total_slides"] > 0:
        progress_pct = round(task["completed_slides"] / task["total_slides"] * 100, 1)

    return {
        "job_id": job_id,
        "status": task["status"],
        "progress_percent": progress_pct,
        "completed_slides": task["completed_slides"],
        "total_slides": task["total_slides"],
        "current_slide": task["current_slide"],
        "current_title": task["current_title"],
        "successful": task["successful"],
        "failed": task["failed"],
        "results": task["results"],
        "error": task.get("error")
    }


@app.post("/api/kodisc/{job_id}/cancel")
async def cancel_kodisc_generation(job_id: str):
    """
    Cancel an in-progress Kodisc video generation.
    """
    if job_id not in kodisc_tasks:
        raise HTTPException(status_code=404, detail="No Kodisc generation task found.")

    task = kodisc_tasks[job_id]

    if task["status"] != "running":
        return {
            "job_id": job_id,
            "status": task["status"],
            "message": f"Task is not running (status: {task['status']})"
        }

    task["cancel_flag"] = True
    logger.info(f"Kodisc cancellation requested for job {job_id}")

    return {
        "job_id": job_id,
        "status": "cancelling",
        "message": "Cancellation requested. Current slide will finish.",
        "completed_so_far": task["completed_slides"]
    }


@app.get("/api/kodisc/{job_id}/videos")
async def get_kodisc_videos(job_id: str):
    """
    Get all generated Kodisc videos for a job.

    This loads from disk cache, so you can revisit without regenerating.
    """
    manifest_path = settings.OUTPUTS_DIR / job_id / "videos" / "kodisc_manifest.json"

    if not manifest_path.exists():
        raise HTTPException(
            status_code=404,
            detail="No Kodisc videos found. Generate them first with POST /api/kodisc/{job_id}/start"
        )

    manifest = json.loads(manifest_path.read_text())

    return {
        "job_id": job_id,
        "total_videos": len(manifest),
        "videos": manifest,
        "source": "kodisc",
        "cached": True
    }
