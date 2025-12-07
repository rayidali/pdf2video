# Paper to Video

Convert research papers into animated explainer videos suitable for 8th graders.

## Overview

This application takes a research paper PDF and converts it into an engaging, animated video explanation using:

- **Mistral OCR** for PDF to markdown conversion
- **Claude AI** for presentation planning and Manim code generation
- **Manim** for 3blue1brown-style animations
- **ElevenLabs** for text-to-speech voiceovers
- **Shotstack** for final video composition

## Setup

1. Create virtual environment:
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Copy `.env.example` to `.env` and fill in your API keys:
```bash
cp .env.example .env
```

4. Run the server:
```bash
uvicorn app.main:app --reload
```

## API Endpoints

- `GET /health` - Health check
- `POST /api/upload` - Upload a PDF file
- `POST /api/process/{job_id}` - Process PDF through OCR
- `GET /api/status/{job_id}` - Get job status
- `GET /api/markdown/{job_id}` - Get extracted markdown

## Usage

1. Upload a PDF:
```bash
curl -X POST -F "file=@paper.pdf" http://localhost:8000/api/upload
```

2. Process through OCR:
```bash
curl -X POST http://localhost:8000/api/process/{job_id}
```

3. Check status:
```bash
curl http://localhost:8000/api/status/{job_id}
```

4. Get extracted markdown:
```bash
curl http://localhost:8000/api/markdown/{job_id}
```

## Project Structure

```
paper-to-video/
├── app/
│   ├── __init__.py
│   ├── main.py                 # FastAPI entry point
│   ├── config.py               # Environment variables
│   ├── models/
│   │   ├── __init__.py
│   │   └── schemas.py          # Pydantic models
│   ├── services/
│   │   ├── __init__.py
│   │   ├── ocr_service.py      # Mistral OCR
│   │   ├── planning_service.py # AI presentation planning
│   │   ├── manim_service.py    # Manim code gen + rendering
│   │   ├── tts_service.py      # ElevenLabs
│   │   └── video_service.py    # Shotstack composition
│   ├── agents/
│   │   ├── __init__.py
│   │   ├── planner_agent.py    # Presentation planner
│   │   └── manim_agent.py      # Manim code generator
│   ├── prompts/
│   │   ├── planner_system.txt
│   │   ├── manim_system.txt
│   │   └── simplifier_system.txt
│   └── utils/
│       ├── __init__.py
│       ├── file_utils.py
│       └── manim_validator.py  # Validate manim code
├── manim_scenes/               # Generated manim files
├── outputs/
│   ├── videos/                 # Rendered manim clips
│   ├── audio/                  # ElevenLabs audio clips
│   └── final/                  # Shotstack output
├── uploads/                    # Uploaded PDFs
├── tests/
├── requirements.txt
├── .env.example
├── .gitignore
└── README.md
```

## License

MIT License
