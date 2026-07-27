"""Async wrapper around the synchronous ``minio`` client — the ``minio``
package makes blocking network calls, so every method offloads to a
worker thread via ``anyio.to_thread.run_sync`` (the standard way FastAPI/
Starlette-adjacent async code calls blocking libraries) rather than
blocking the event loop. Shared by any ``ChannelProvider``'s
``upload_attachment``/``download_attachment``, the conversation engine's
attachment persistence, and ``CompanyService``'s logo upload (same
bucket, ``logos/`` key prefix — see ``docs/architecture/web-chat.md``
and ``docs/architecture/administration.md``).
"""

import io

from anyio import to_thread
from minio import Minio


class AttachmentStore:
    def __init__(self, client: Minio, *, bucket: str) -> None:
        self._client = client
        self._bucket = bucket

    async def ensure_bucket(self) -> None:
        exists = await to_thread.run_sync(self._client.bucket_exists, self._bucket)
        if not exists:
            await to_thread.run_sync(self._client.make_bucket, self._bucket)

    async def upload(self, *, key: str, data: bytes, content_type: str) -> None:
        await to_thread.run_sync(self._upload_sync, key, data, content_type)

    def _upload_sync(self, key: str, data: bytes, content_type: str) -> None:
        self._client.put_object(
            self._bucket, key, io.BytesIO(data), length=len(data), content_type=content_type
        )

    async def download(self, *, key: str) -> bytes:
        return await to_thread.run_sync(self._download_sync, key)

    def _download_sync(self, key: str) -> bytes:
        response = self._client.get_object(self._bucket, key)
        try:
            return bytes(response.read())
        finally:
            response.close()
            response.release_conn()

    async def delete(self, *, key: str) -> None:
        await to_thread.run_sync(self._client.remove_object, self._bucket, key)

    async def health_check(self) -> bool:
        try:
            await to_thread.run_sync(self._client.bucket_exists, self._bucket)
        except Exception:
            return False
        return True
