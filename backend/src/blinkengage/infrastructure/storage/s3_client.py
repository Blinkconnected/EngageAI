"""MinIO/S3-compatible object storage client factory. See
``docs/architecture/web-chat.md`` — built here for
``ChannelProvider.upload_attachment``/``download_attachment``, reused by
M13's `message_attachments` persistence.
"""

from urllib.parse import urlsplit

from minio import Minio

from blinkengage.core.config import Settings


def create_minio_client(settings: Settings) -> Minio:
    endpoint = urlsplit(settings.s3_endpoint_url).netloc or settings.s3_endpoint_url
    return Minio(
        endpoint,
        access_key=settings.s3_access_key,
        secret_key=settings.s3_secret_key,
        secure=settings.s3_use_ssl,
    )
