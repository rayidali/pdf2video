"""Local PDF text extraction with pypdf. Free, fast, no vendor.

Good enough for born-digital papers (arXiv, journals). Scanned PDFs yield little or no
text; the caller falls back to Mistral OCR in that case if a key is configured.
"""
import io
import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)

MIN_CHARS_PER_PAGE = 150   # below this the PDF is probably scanned or image-only
MIN_TOTAL_CHARS = 800


@dataclass
class ExtractedText:
    text: str
    pages: int
    chars: int

    @property
    def looks_complete(self) -> bool:
        if self.pages == 0 or self.chars < MIN_TOTAL_CHARS:
            return False
        return (self.chars / self.pages) >= MIN_CHARS_PER_PAGE


def extract_text(pdf_bytes: bytes) -> ExtractedText:
    try:
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(pdf_bytes))
        parts = []
        for page in reader.pages:
            try:
                parts.append((page.extract_text() or "").strip())
            except Exception as e:  # one bad page should not sink the paper
                logger.warning(f"[pdf] page extraction failed: {e}")
                parts.append("")
        text = "\n\n---\n\n".join(p for p in parts if p)
        result = ExtractedText(text=text, pages=len(reader.pages), chars=len(text))
        logger.info(f"[pdf] pypdf extracted {result.chars} chars from {result.pages} pages")
        return result
    except Exception as e:
        logger.warning(f"[pdf] pypdf could not read the file: {e}")
        return ExtractedText(text="", pages=0, chars=0)
