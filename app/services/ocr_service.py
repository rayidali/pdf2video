import httpx
import base64
import logging
import fitz  # PyMuPDF

logger = logging.getLogger(__name__)


class MistralOCRService:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = "https://api.mistral.ai/v1"

    def _pdf_to_images(self, pdf_path: str) -> list[str]:
        """
        Convert PDF pages to base64-encoded PNG images.
        """
        images = []
        doc = fitz.open(pdf_path)

        for page_num in range(len(doc)):
            page = doc[page_num]
            # Render page to image (2x zoom for better quality)
            mat = fitz.Matrix(2, 2)
            pix = page.get_pixmap(matrix=mat)
            img_bytes = pix.tobytes("png")
            img_base64 = base64.standard_b64encode(img_bytes).decode("utf-8")
            images.append(img_base64)
            logger.info(f"Converted page {page_num + 1}/{len(doc)} to image")

        doc.close()
        return images

    async def _ocr_image(self, client: httpx.AsyncClient, img_base64: str, page_num: int, total_pages: int) -> str:
        """
        OCR a single image using Mistral's vision model.
        """
        response = await client.post(
            f"{self.base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            },
            json={
                "model": "pixtral-12b-2409",
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/png;base64,{img_base64}"
                                }
                            },
                            {
                                "type": "text",
                                "text": f"""Extract all text from this image (page {page_num} of {total_pages} of a research paper) and convert it to well-structured markdown.

Requirements:
- Preserve all headings with proper markdown hierarchy (# ## ###)
- Keep equations in LaTeX format wrapped in $ or $$
- Preserve tables using markdown table syntax
- Include figure captions as blockquotes
- Maintain the logical flow and structure
- Do NOT include any preamble like "Here is the extracted text" - just output the markdown directly"""
                            }
                        ]
                    }
                ],
                "max_tokens": 4000
            },
            timeout=120.0
        )

        if response.status_code != 200:
            logger.error(f"Mistral API error on page {page_num}: {response.status_code} - {response.text}")
            raise Exception(f"Mistral API error: {response.status_code} - {response.text}")

        result = response.json()
        return result["choices"][0]["message"]["content"]

    async def pdf_to_markdown(self, pdf_path: str) -> str:
        """
        Convert PDF to markdown using Mistral's OCR capability.
        Converts each page to an image and processes them sequentially.
        """
        logger.info(f"Starting OCR processing for: {pdf_path}")

        # Convert PDF to images
        images = self._pdf_to_images(pdf_path)
        total_pages = len(images)
        logger.info(f"PDF has {total_pages} pages")

        # OCR each page
        markdown_parts = []
        async with httpx.AsyncClient() as client:
            for i, img_base64 in enumerate(images):
                page_num = i + 1
                logger.info(f"Processing page {page_num}/{total_pages}")

                page_markdown = await self._ocr_image(client, img_base64, page_num, total_pages)
                markdown_parts.append(page_markdown)

                logger.info(f"Page {page_num} completed")

        # Combine all pages
        markdown_content = "\n\n---\n\n".join(markdown_parts)

        logger.info(f"OCR completed. Extracted {len(markdown_content)} characters from {total_pages} pages")
        return markdown_content
