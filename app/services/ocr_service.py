import httpx
import base64
import logging

logger = logging.getLogger(__name__)


class MistralOCRService:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = "https://api.mistral.ai/v1"

    async def pdf_to_markdown(self, pdf_path: str) -> str:
        """
        Convert PDF to markdown using Mistral's OCR capability.
        """
        logger.info(f"Starting OCR processing for: {pdf_path}")

        # Read and encode PDF
        with open(pdf_path, "rb") as f:
            pdf_base64 = base64.standard_b64encode(f.read()).decode("utf-8")

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": "pixtral-12b-2409",  # Vision model for PDF
                    "messages": [
                        {
                            "role": "user",
                            "content": [
                                {
                                    "type": "image_url",
                                    "image_url": {
                                        "url": f"data:application/pdf;base64,{pdf_base64}"
                                    }
                                },
                                {
                                    "type": "text",
                                    "text": """Extract all text from this research paper and convert it to well-structured markdown.

Requirements:
- Preserve all headings with proper markdown hierarchy (# ## ###)
- Keep equations in LaTeX format wrapped in $ or $$
- Preserve tables using markdown table syntax
- Include figure captions as blockquotes
- Maintain the logical flow and structure of the paper
- Extract text from all pages"""
                                }
                            ]
                        }
                    ],
                    "max_tokens": 16000
                },
                timeout=180.0
            )

            if response.status_code != 200:
                logger.error(f"Mistral API error: {response.status_code} - {response.text}")
                raise Exception(f"Mistral API error: {response.status_code} - {response.text}")

            result = response.json()
            markdown_content = result["choices"][0]["message"]["content"]

            logger.info(f"OCR completed. Extracted {len(markdown_content)} characters")
            return markdown_content
