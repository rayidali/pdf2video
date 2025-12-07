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

## Deploy to Render

1. Go to [render.com](https://render.com) and sign up/login

2. Click **New +** → **Web Service**

3. Connect your GitHub repo

4. Configure the service:
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `uvicorn app.main:app --host 0.0.0.0 --port $PORT`

5. Add environment variables in the Render dashboard:
   - `MISTRAL_API_KEY` - Your Mistral API key
   - `ANTHROPIC_API_KEY` - Your Anthropic API key

6. Click **Create Web Service**

Your app will be live at `https://your-app-name.onrender.com`

**Render advantages over Vercel:**
- Longer timeouts (better for OCR processing)
- Persistent filesystem during instance lifetime
- Better suited for Python backends

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
├── render.yaml                 # Render deployment config
├── requirements.txt
├── .env.example
└── .gitignore
```

## License

MIT License
