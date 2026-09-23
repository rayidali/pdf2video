"""Mistral OCR: PDF bytes in, markdown out. Never touches the filesystem.

Mistral's free tier allows about one request per second, and this flow makes three calls
in a row (upload, signed URL, OCR), so every call retries on 429/5xx with backoff.
"""
import asyncio
import logging

import httpx

logger = logging.getLogger(__name__)

RETRY_STATUSES = {429, 500, 502, 503, 504}
MAX_ATTEMPTS = 5
BACKOFF_SECONDS = (1.5, 3, 6, 10)


async def _with_retry(label: str, send) -> httpx.Response:
    """Call `send()` until it returns a non-retryable status. Honours Retry-After."""
    last: httpx.Response | None = None
    for attempt in range(MAX_ATTEMPTS):
        response = await send()
        if response.status_code not in RETRY_STATUSES:
            return response
        last = response
        if attempt == MAX_ATTEMPTS - 1:
            break
        wait = BACKOFF_SECONDS[min(attempt, len(BACKOFF_SECONDS) - 1)]
        retry_after = response.headers.get("retry-after")
        if retry_after and retry_after.isdigit():
            wait = max(wait, float(retry_after))
        logger.warning(f"[OCR] {label} HTTP {response.status_code}; retry {attempt + 1}/{MAX_ATTEMPTS - 1} in {wait}s")
        await asyncio.sleep(wait)
    return last  # type: ignore[return-value]


class MistralOCRService:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = "https://api.mistral.ai/v1"
        self.headers = {"Authorization": f"Bearer {api_key}"}

    def is_configured(self) -> bool:
        return bool(self.api_key)

    async def _upload_file(self, client: httpx.AsyncClient, pdf_bytes: bytes, filename: str) -> str:
        files = {"file": (filename, pdf_bytes, "application/pdf"), "purpose": (None, "ocr")}
        response = await _with_retry(
            "upload",
            lambda: client.post(f"{self.base_url}/files", headers=self.headers, files=files, timeout=120.0),
        )
        if response.status_code != 200:
            raise RuntimeError(f"Mistral file upload failed: {response.status_code} - {response.text[:300]}")
        file_id = response.json()["id"]
        logger.info(f"[OCR] uploaded {filename} as {file_id}")
        return file_id

    async def _get_signed_url(self, client: httpx.AsyncClient, file_id: str) -> str:
        response = await _with_retry(
            "signed-url",
            lambda: client.get(
                f"{self.base_url}/files/{file_id}/url", headers=self.headers, params={"expiry": 24}, timeout=30.0
            ),
        )
        if response.status_code != 200:
            raise RuntimeError(f"Mistral signed URL failed: {response.status_code} - {response.text[:300]}")
        return response.json()["url"]

    async def _run_ocr(self, client: httpx.AsyncClient, document_url: str) -> dict:
        response = await _with_retry(
            "ocr",
            lambda: client.post(
                f"{self.base_url}/ocr",
                headers={**self.headers, "Content-Type": "application/json"},
                json={
                    "model": "mistral-ocr-latest",
                    "document": {"type": "document_url", "document_url": document_url},
                    "include_image_base64": False,
                },
                timeout=240.0,
            ),
        )
        if response.status_code != 200:
            raise RuntimeError(f"Mistral OCR failed: {response.status_code} - {response.text[:300]}")
        return response.json()

    @staticmethod
    def _to_markdown(ocr_result: dict) -> str:
        parts = []
        for page in ocr_result.get("pages", []):
            text = page.get("markdown") or page.get("text") or ""
            if text:
                parts.append(text)
        return "\n\n---\n\n".join(parts)

    async def pdf_to_markdown(self, pdf_bytes: bytes, filename: str = "paper.pdf") -> str:
        if not self.is_configured():
            raise RuntimeError("MISTRAL_API_KEY not configured")
        logger.info(f"[OCR] start {filename} ({len(pdf_bytes)} bytes)")
        async with httpx.AsyncClient() as client:
            file_id = await self._upload_file(client, pdf_bytes, filename)
            signed_url = await self._get_signed_url(client, file_id)
            result = await self._run_ocr(client, signed_url)
        markdown = self._to_markdown(result)
        logger.info(f"[OCR] done: {len(markdown)} chars")
        return markdown
