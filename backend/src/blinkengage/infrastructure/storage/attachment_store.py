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

    async def download_range(self, *, key: str, offset: int, length: int | None) -> bytes:
        """Part of an object, for an HTTP range request.

        What makes dragging a video's scrubber work. Without it a browser
        must download an entire file before it can play any of it, and
        seeking backwards means downloading it again — so a customer's
        50 MB video is effectively unplayable.

        ``length=None`` means "to the end", which is what a browser sends
        as ``Range: bytes=0-`` when it starts playing without knowing how
        much it will need.
        """
        return await to_thread.run_sync(self._download_range_sync, key, offset, length)

    def _download_range_sync(self, key: str, offset: int, length: int | None) -> bytes:
        response = self._client.get_object(self._bucket, key, offset=offset, length=length or 0)
        try:
            return bytes(response.read())
        finally:
            response.close()
            response.release_conn()

    async def size(self, *, key: str) -> int:
        """The object's length, for ``Content-Length`` and range maths.

        A separate HEAD-equivalent rather than reading the object: a range
        response has to state the total size, and downloading a file to
        find out how big it is defeats the point of ranges entirely.
        """
        stat = await to_thread.run_sync(self._client.stat_object, self._bucket, key)
        return int(stat.size or 0)

    async def delete(self, *, key: str) -> None:
        await to_thread.run_sync(self._client.remove_object, self._bucket, key)

    async def health_check(self) -> bool:
        try:
            await to_thread.run_sync(self._client.bucket_exists, self._bucket)
        except Exception:
            return False
        return True
