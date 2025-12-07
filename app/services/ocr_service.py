import httpx
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


class MistralOCRService:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = "https://api.mistral.ai/v1"
        self.headers = {
            "Authorization": f"Bearer {api_key}"
        }

    async def _upload_file(self, client: httpx.AsyncClient, pdf_path: str) -> str:
        """
        Step 1: Upload PDF to Mistral for OCR processing.
        Returns the file ID.
        """
        file_name = Path(pdf_path).name

        with open(pdf_path, "rb") as f:
            files = {
                "file": (file_name, f, "application/pdf"),
                "purpose": (None, "ocr")
            }
            response = await client.post(
                f"{self.base_url}/files",
                headers=self.headers,
                files=files,
                timeout=120.0
            )

        if response.status_code != 200:
            logger.error(f"File upload failed: {response.status_code} - {response.text}")
            raise Exception(f"File upload failed: {response.status_code} - {response.text}")

        result = response.json()
        file_id = result["id"]
        logger.info(f"File uploaded successfully. ID: {file_id}")
        return file_id

    async def _get_signed_url(self, client: httpx.AsyncClient, file_id: str) -> str:
        """
        Step 2: Get a signed URL for the uploaded file.
        """
        response = await client.get(
            f"{self.base_url}/files/{file_id}/url",
            headers=self.headers,
            params={"expiry": 24},
            timeout=30.0
        )

        if response.status_code != 200:
            logger.error(f"Failed to get signed URL: {response.status_code} - {response.text}")
            raise Exception(f"Failed to get signed URL: {response.status_code} - {response.text}")

        result = response.json()
        signed_url = result["url"]
        logger.info(f"Got signed URL for file {file_id}")
        return signed_url

    async def _run_ocr(self, client: httpx.AsyncClient, document_url: str) -> dict:
        """
        Step 3: Run OCR on the document using the signed URL.
        """
        response = await client.post(
            f"{self.base_url}/ocr",
            headers={
                **self.headers,
                "Content-Type": "application/json"
            },
            json={
                "model": "mistral-ocr-latest",
                "document": {
                    "type": "document_url",
                    "document_url": document_url
                },
                "include_image_base64": False  # Don't need images, just text
            },
            timeout=300.0  # OCR can take a while for long documents
        )

        if response.status_code != 200:
            logger.error(f"OCR failed: {response.status_code} - {response.text}")
            raise Exception(f"OCR failed: {response.status_code} - {response.text}")

        result = response.json()
        logger.info("OCR completed successfully")
        return result

    def _convert_to_markdown(self, ocr_result: dict) -> str:
        """
        Convert Mistral OCR result to markdown.
        """
        markdown_parts = []

        # OCR result contains pages with text content
        pages = ocr_result.get("pages", [])

        for i, page in enumerate(pages):
            page_text = page.get("markdown", "") or page.get("text", "")
            if page_text:
                markdown_parts.append(page_text)

        # Join pages with separators
        markdown_content = "\n\n---\n\n".join(markdown_parts)

        return markdown_content

    async def pdf_to_markdown(self, pdf_path: str) -> str:
        """
        Convert PDF to markdown using Mistral's OCR API.

        Flow:
        1. Upload PDF to Mistral
        2. Get signed URL
        3. Run OCR
        4. Convert result to markdown
        """
        logger.info(f"Starting OCR processing for: {pdf_path}")

        async with httpx.AsyncClient() as client:
            # Step 1: Upload file
            file_id = await self._upload_file(client, pdf_path)

            # Step 2: Get signed URL
            signed_url = await self._get_signed_url(client, file_id)

            # Step 3: Run OCR
            ocr_result = await self._run_ocr(client, signed_url)

            # Step 4: Convert to markdown
            markdown_content = self._convert_to_markdown(ocr_result)

        logger.info(f"OCR completed. Extracted {len(markdown_content)} characters")
        return markdown_content
