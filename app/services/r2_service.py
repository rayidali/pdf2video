"""Cloudflare R2 uploads (S3-compatible). boto3 is sync, so callers use upload_async()."""
import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class UploadResult:
    success: bool
    public_url: Optional[str] = None
    file_name: Optional[str] = None
    error: Optional[str] = None


class R2Service:
    def __init__(self, access_key_id: str, secret_access_key: str, endpoint_url: str, bucket_name: str, public_url_base: str):
        self.access_key_id = access_key_id
        self.secret_access_key = secret_access_key
        self.endpoint_url = endpoint_url
        self.bucket_name = bucket_name
        self.public_url_base = (public_url_base or "").rstrip("/")
        self._client = None

    def is_configured(self) -> bool:
        return bool(self.access_key_id and self.secret_access_key and self.endpoint_url and self.bucket_name and self.public_url_base)

    def _get_client(self):
        if self._client is None:
            import boto3
            from botocore.config import Config

            self._client = boto3.client(
                "s3",
                endpoint_url=self.endpoint_url,
                aws_access_key_id=self.access_key_id,
                aws_secret_access_key=self.secret_access_key,
                config=Config(signature_version="s3v4", retries={"max_attempts": 3}),
            )
        return self._client

    def upload_file(self, file_data: bytes, file_name: str, content_type: str = "audio/mpeg") -> UploadResult:
        if not self.is_configured():
            return UploadResult(success=False, error="R2 credentials not configured")
        try:
            from botocore.exceptions import ClientError
        except ImportError:  # pragma: no cover
            ClientError = Exception
        try:
            client = self._get_client()
            logger.info(f"[R2] uploading {file_name} ({len(file_data)} bytes)")
            client.put_object(Bucket=self.bucket_name, Key=file_name, Body=file_data, ContentType=content_type)
            public_url = f"{self.public_url_base}/{file_name}?v={int(time.time() * 1000)}"
            return UploadResult(success=True, public_url=public_url, file_name=file_name)
        except ClientError as e:  # type: ignore[misc]
            err = e.response.get("Error", {})
            logger.error(f"[R2] {err.get('Code')}: {err.get('Message')}")
            return UploadResult(success=False, error=f"R2 error {err.get('Code')}: {err.get('Message')}")
        except Exception as e:
            logger.error(f"[R2] upload error: {e}")
            return UploadResult(success=False, error=str(e))

    async def upload_async(self, file_data: bytes, file_name: str, content_type: str = "audio/mpeg") -> UploadResult:
        return await asyncio.to_thread(self.upload_file, file_data, file_name, content_type)
