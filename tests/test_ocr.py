import asyncio
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.ocr_service import MistralOCRService
from app.config import settings


async def test_ocr():
    """Test the OCR service with a sample PDF."""
    service = MistralOCRService(settings.MISTRAL_API_KEY)

    # Test with a sample PDF (you'll need to provide one)
    pdf_path = "test_paper.pdf"

    if not Path(pdf_path).exists():
        print(f"Error: Test PDF not found at {pdf_path}")
        print("Please provide a test PDF file named 'test_paper.pdf'")
        return

    try:
        markdown = await service.pdf_to_markdown(pdf_path)
        print("OCR Result Preview:")
        print("-" * 50)
        print(markdown[:1000])
        print("-" * 50)
        print(f"Total length: {len(markdown)} characters")
    except Exception as e:
        print(f"Error: {e}")


if __name__ == "__main__":
    asyncio.run(test_ocr())
