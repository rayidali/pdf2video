"""Cloudflare R2 (S3-compatible) storage.

Objects are private. Readers get presigned GET URLs (up to 7 days), minted fresh on each
read, so the bucket never needs public access. boto3 is sync, so callers use the
*_async wrappers.
"""
import asyncio
import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)

PRESIGN_SECONDS = 7 * 24 * 3600  # S3 SigV4 maximum


@dataclass
class UploadResult:
    success: bool
    key: Optional[str] = None
    public_url: Optional[str] = None   # presigned GET URL
    error: Optional[str] = None


class R2Service:
    def __init__(self, access_key_id: str, secret_access_key: str, endpoint_url: str, bucket_name: str, public_url_base: str = ""):
        self.access_key_id = access_key_id
        self.secret_access_key = secret_access_key
        self.endpoint_url = endpoint_url
        self.bucket_name = bucket_name
        self.public_url_base = (public_url_base or "").rstrip("/")  # unused unless you make the bucket public
        self._client = None

    def is_configured(self) -> bool:
        return bool(self.access_key_id and self.secret_access_key and self.endpoint_url and self.bucket_name)

    def _get_client(self):
        if self._client is None:
            import boto3
            from botocore.config import Config

            self._client = boto3.client(
                "s3",
                endpoint_url=self.endpoint_url,
                aws_access_key_id=self.access_key_id,
                aws_secret_access_key=self.secret_access_key,
                region_name="auto",
                config=Config(signature_version="s3v4", retries={"max_attempts": 3}),
            )
        return self._client

    def presign(self, key: str, expires: int = PRESIGN_SECONDS) -> Optional[str]:
        if not self.is_configured() or not key:
            return None
        try:
            return self._get_client().generate_presigned_url(
                "get_object", Params={"Bucket": self.bucket_name, "Key": key}, ExpiresIn=expires
            )
        except Exception as e:
            logger.error(f"[R2] presign failed for {key}: {e}")
            return None

    def upload_file(self, file_data: bytes, file_name: str, content_type: str = "audio/mpeg") -> UploadResult:
        if not self.is_configured():
            return UploadResult(success=False, error="R2 credentials not configured")
        try:
            client = self._get_client()
            logger.info(f"[R2] uploading {file_name} ({len(file_data)} bytes)")
            client.put_object(Bucket=self.bucket_name, Key=file_name, Body=file_data, ContentType=content_type)
            return UploadResult(success=True, key=file_name, public_url=self.presign(file_name))
        except Exception as e:
            code = getattr(getattr(e, "response", None), "get", lambda *_: None)("Error") or {}
            logger.error(f"[R2] upload error: {code or e}")
            return UploadResult(success=False, error=f"R2 error: {code.get('Code') + ' ' + code.get('Message', '') if code else e}")

    async def upload_async(self, file_data: bytes, file_name: str, content_type: str = "audio/mpeg") -> UploadResult:
        return await asyncio.to_thread(self.upload_file, file_data, file_name, content_type)

    async def presign_async(self, key: str) -> Optional[str]:
        return await asyncio.to_thread(self.presign, key)
