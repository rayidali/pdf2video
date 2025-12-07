# Vercel serverless function entry point
from app.main import app

# Export the FastAPI app for Vercel
handler = app
