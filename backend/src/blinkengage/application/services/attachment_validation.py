"""Attachment type/size validation. Virus scanning (e.g. ClamAV) is a
deliberately deferred extension point, not a stubbed-out scanner that
always says "clean" — see ``docs/architecture/conversations.md`` decision
#4.
"""

from dataclasses import dataclass

from blinkengage.core.config import Settings


@dataclass(frozen=True, slots=True)
class AttachmentValidationResult:
    approved: bool
    reason: str | None = None


def validate_attachment(
    *, content_type: str, size_bytes: int, settings: Settings
) -> AttachmentValidationResult:
    if size_bytes > settings.attachment_max_size_bytes:
        return AttachmentValidationResult(
            approved=False,
            reason=(
                f"File size {size_bytes} bytes exceeds the maximum of "
                f"{settings.attachment_max_size_bytes} bytes"
            ),
        )
    if content_type not in settings.attachment_allowed_content_types:
        return AttachmentValidationResult(
            approved=False, reason=f"Content type {content_type!r} is not allowed"
        )
    return AttachmentValidationResult(approved=True)


def validate_logo(
    *, content_type: str, size_bytes: int, settings: Settings
) -> AttachmentValidationResult:
    """Same shape as ``validate_attachment``, against the tighter
    ``logo_*`` limits — a logo is always a small raster image, never a
    document, so it doesn't share the generic attachment allow-list."""
    if size_bytes > settings.logo_max_size_bytes:
        return AttachmentValidationResult(
            approved=False,
            reason=(
                f"File size {size_bytes} bytes exceeds the maximum of "
                f"{settings.logo_max_size_bytes} bytes"
            ),
        )
    if content_type not in settings.logo_allowed_content_types:
        return AttachmentValidationResult(
            approved=False, reason=f"Content type {content_type!r} is not allowed"
        )
    return AttachmentValidationResult(approved=True)
