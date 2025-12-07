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

5. Open http://localhost:8000 in your browser

## Deploy to Vercel

1. Install Vercel CLI:
```bash
npm i -g vercel
```

2. Add your environment variables in Vercel:
```bash
vercel secrets add mistral_api_key "your-key-here"
vercel secrets add anthropic_api_key "your-key-here"
```

3. Deploy:
```bash
vercel
```

**Note:** Vercel has limitations for serverless functions:
- 10s timeout on free tier (60s on Pro)
- No persistent filesystem (uploads don't persist between requests)
- Best suited for demo/testing purposes

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
├── api/
│   └── index.py                # Vercel serverless entry point
├── app/
│   ├── __init__.py
│   ├── main.py                 # FastAPI application
│   ├── config.py               # Environment variables
│   ├── models/
│   │   └── schemas.py          # Pydantic models
│   ├── services/
│   │   └── ocr_service.py      # Mistral OCR
│   ├── agents/                 # (Phase 2+)
│   ├── prompts/                # (Phase 2+)
│   └── utils/
├── static/
│   ├── index.html              # Frontend UI
│   ├── style.css               # Styles
│   └── app.js                  # Frontend JavaScript
├── tests/
│   └── test_ocr.py
├── vercel.json                 # Vercel deployment config
├── requirements.txt
├── .env.example
└── .gitignore
```

## License

MIT License
