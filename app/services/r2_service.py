"""
Cloudflare R2 Storage Service

Uploads files to Cloudflare R2 (S3-compatible) and returns public URLs.
"""

import logging
from dataclasses import dataclass
from typing import Optional
import time

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)


@dataclass
class UploadResult:
    """Result from file upload."""
    success: bool
    public_url: Optional[str] = None
    file_name: Optional[str] = None
    error: Optional[str] = None


class R2Service:
    """Service for uploading files to Cloudflare R2."""

    def __init__(
        self,
        access_key_id: str,
        secret_access_key: str,
        endpoint_url: str,
        bucket_name: str,
        public_url_base: str
    ):
        self.access_key_id = access_key_id
        self.secret_access_key = secret_access_key
        self.endpoint_url = endpoint_url
        self.bucket_name = bucket_name
        self.public_url_base = public_url_base.rstrip('/')

        # Initialize S3 client (R2 is S3-compatible)
        self._client = None

    def is_configured(self) -> bool:
        """Check if service is configured."""
        return bool(self.access_key_id and self.secret_access_key)

    def _get_client(self):
        """Get or create S3 client."""
        if self._client is None:
            self._client = boto3.client(
                's3',
                endpoint_url=self.endpoint_url,
                aws_access_key_id=self.access_key_id,
                aws_secret_access_key=self.secret_access_key,
                config=Config(
                    signature_version='s3v4',
                    retries={'max_attempts': 3}
                )
            )
        return self._client

    def upload_file(
        self,
        file_data: bytes,
        file_name: str,
        content_type: str = "audio/mpeg"
    ) -> UploadResult:
        """
        Upload a file to R2 and return the public URL.

        Args:
            file_data: Raw file bytes
            file_name: Name to save as (e.g., "s001.mp3")
            content_type: MIME type of the file

        Returns:
            UploadResult with public_url if successful
        """
        if not self.is_configured():
            return UploadResult(
                success=False,
                error="R2 credentials not configured"
            )

        try:
            client = self._get_client()

            logger.info(f"Uploading {file_name} ({len(file_data)} bytes) to R2...")

            # Upload to R2
            client.put_object(
                Bucket=self.bucket_name,
                Key=file_name,
                Body=file_data,
                ContentType=content_type
            )

            # Generate public URL with cache-busting timestamp
            timestamp = int(time.time() * 1000)
            public_url = f"{self.public_url_base}/{file_name}?v={timestamp}"

            logger.info(f"Uploaded to R2: {public_url}")

            return UploadResult(
                success=True,
                public_url=public_url,
                file_name=file_name
            )

        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', 'Unknown')
            error_msg = e.response.get('Error', {}).get('Message', str(e))
            logger.error(f"R2 upload error: {error_code} - {error_msg}")
            return UploadResult(
                success=False,
                error=f"R2 error {error_code}: {error_msg}"
            )
        except Exception as e:
            logger.error(f"R2 upload error: {e}")
            return UploadResult(
                success=False,
                error=str(e)
            )

    def delete_file(self, file_name: str) -> bool:
        """Delete a file from R2."""
        if not self.is_configured():
            return False

        try:
            client = self._get_client()
            client.delete_object(Bucket=self.bucket_name, Key=file_name)
            logger.info(f"Deleted from R2: {file_name}")
            return True
        except Exception as e:
            logger.error(f"R2 delete error: {e}")
            return False
