"""Reading pixel dimensions from an uploaded file.

See ``docs/architecture/conversations.md``.

Used so the conversation can reserve the right amount of space *before* an
image loads. Without it a thread of photos reflows as each arrives, and on
a long conversation that means an agent loses their place mid-sentence.

**Never raises.** A file whose dimensions cannot be read is not a failed
upload — the attachment is still perfectly valid and downloadable, and the
UI already handles unknown dimensions for video and documents. Refusing an
upload because a header was unusual would turn a cosmetic nicety into lost
customer messages, which is the wrong trade by a wide margin.
"""

import io

from PIL import Image, UnidentifiedImageError

from blinkengage.core.logging import get_logger
from blinkengage.domain.media import has_measurable_dimensions

logger = get_logger(__name__)


def measure(*, content_type: str, data: bytes) -> tuple[int | None, int | None]:
    """``(width, height)``, or ``(None, None)`` when unknown.

    Only the header is parsed — ``Image.open`` is lazy and ``.size`` does
    not decode the pixels — so this costs microseconds regardless of how
    large the image is, and never materialises a decompressed bitmap.
    Pillow's own decompression-bomb guard stays enabled, since this runs on
    attacker-supplied bytes.
    """
    if not has_measurable_dimensions(content_type):
        return None, None

    try:
        with Image.open(io.BytesIO(data)) as image:
            width, height = image.size
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
        # Includes the case where the declared content type says image and
        # the bytes disagree. Debug, not warning: it is not an error, it
        # just means the thread reserves a default box for this one.
        logger.debug("attachment_dimensions_unreadable", content_type=content_type)
        return None, None

    if width <= 0 or height <= 0:
        return None, None
    return width, height


__all__ = ["measure"]
