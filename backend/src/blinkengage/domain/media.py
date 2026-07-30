"""How an attachment is presented: its kind, and whether it can be shown.

See ``docs/architecture/conversations.md``.

An agent handling a conversation needs to *see* what a customer sent. A
screenshot of an error message, a photo of a damaged delivery, a voice
note describing a problem — each is the substance of the conversation, and
a row of grey "download" chips makes an agent open six files to find the
one that matters.

So the decision this module makes is: what is this file, and can the
browser render it inline. Framework-free, like the rest of ``domain/``, so
the API schema, the upload path and the tests share one answer.

**Deliberately conservative.** A kind is claimed only when browsers
genuinely render it without a plugin or a library. Being wrong towards
"just offer a download" costs a click; being wrong the other way shows a
broken element where the customer's photo should be, which is worse
because it looks like the file is corrupt.
"""

from enum import StrEnum
from typing import Final


class MediaKind(StrEnum):
    """What an attachment is, for presentation purposes.

    Not the MIME type — that is far too granular for a UI decision, and a
    component switching on forty content types is a component nobody
    maintains correctly.
    """

    IMAGE = "image"
    VIDEO = "video"
    AUDIO = "audio"
    #: Renderable in a browser frame but not as media — a PDF.
    DOCUMENT = "document"
    #: Everything else. Offered as a download, never as a broken preview.
    FILE = "file"


#: Image types every current browser decodes. Deliberately explicit rather
#: than ``image/*``: SVG is an image by MIME type and an **executable
#: document** in practice, so it is excluded and treated as a file — an
#: inline SVG from a customer is a script-injection surface.
_IMAGE_TYPES: Final[frozenset[str]] = frozenset(
    {
        "image/jpeg",
        "image/jpg",
        "image/png",
        "image/gif",
        "image/webp",
        "image/avif",
        "image/bmp",
        "image/x-ms-bmp",
        "image/tiff",
        "image/heic",
        "image/heif",
    }
)

#: Types where ``<img>`` is likely to fail even though the file is a real
#: image. HEIC/HEIF only decode natively on Apple platforms, and TIFF
#: barely anywhere — so they are classified IMAGE (for the icon and the
#: lightbox affordance) but flagged as needing a fallback, rather than
#: rendered as a broken image and blamed on the customer.
UNRELIABLE_IMAGE_TYPES: Final[frozenset[str]] = frozenset(
    {"image/heic", "image/heif", "image/tiff", "image/bmp", "image/x-ms-bmp"}
)

#: Containers browsers play. ``video/quicktime`` (.mov, what an iPhone
#: sends) plays in Safari and usually in Chrome when the codec is H.264,
#: which it almost always is.
_VIDEO_TYPES: Final[frozenset[str]] = frozenset(
    {"video/mp4", "video/webm", "video/ogg", "video/quicktime"}
)

_AUDIO_TYPES: Final[frozenset[str]] = frozenset(
    {
        "audio/mpeg",
        "audio/mp3",
        "audio/mp4",
        "audio/aac",
        "audio/ogg",
        "audio/opus",
        "audio/wav",
        "audio/x-wav",
        "audio/webm",
        # WhatsApp voice notes arrive as this.
        "audio/ogg; codecs=opus",
    }
)

_DOCUMENT_TYPES: Final[frozenset[str]] = frozenset({"application/pdf"})


def _normalise(content_type: str) -> str:
    """Lowercased, without parameters.

    A channel may send ``audio/ogg; codecs=opus`` or ``image/JPEG``, and a
    lookup that misses on either would offer a download for a voice note
    the browser can play perfectly well.
    """
    return content_type.split(";")[0].strip().lower()


def kind_for(content_type: str) -> MediaKind:
    normalised = _normalise(content_type)
    if normalised in _IMAGE_TYPES:
        return MediaKind.IMAGE
    if normalised in _VIDEO_TYPES:
        return MediaKind.VIDEO
    if normalised in _AUDIO_TYPES:
        return MediaKind.AUDIO
    if normalised in _DOCUMENT_TYPES:
        return MediaKind.DOCUMENT
    return MediaKind.FILE


def is_inline_renderable(content_type: str) -> bool:
    """Whether the browser can show this in the conversation itself."""
    return kind_for(content_type) in {MediaKind.IMAGE, MediaKind.VIDEO, MediaKind.AUDIO}


def may_need_fallback(content_type: str) -> bool:
    """An image the browser may refuse to decode.

    Surfaced so the UI can offer "open in a new tab" prominently instead of
    showing a broken image and leaving an agent thinking the customer sent
    a corrupt file.
    """
    return _normalise(content_type) in UNRELIABLE_IMAGE_TYPES


def has_measurable_dimensions(content_type: str) -> bool:
    """Whether pixel dimensions can be read from the file cheaply.

    Images only. Video dimensions need a demuxer this deployment does not
    carry, so video reserves a 16:9 box instead — right for the
    overwhelming majority of what phones record, and honest about being an
    assumption.
    """
    return kind_for(content_type) is MediaKind.IMAGE


#: What a video's placeholder reserves before its metadata loads. Phones
#: record 16:9, and reserving the common case means the thread does not
#: jump for it.
DEFAULT_VIDEO_ASPECT_RATIO: Final[float] = 16 / 9

#: Beyond this, an image is shown at a bounded size in the thread and the
#: full resolution is left to the lightbox. A customer's 4000px screenshot
#: rendered at full width is both unreadable and a waste of a phone's data.
MAX_INLINE_EDGE_PX: Final[int] = 1600


__all__ = [
    "DEFAULT_VIDEO_ASPECT_RATIO",
    "MAX_INLINE_EDGE_PX",
    "UNRELIABLE_IMAGE_TYPES",
    "MediaKind",
    "has_measurable_dimensions",
    "is_inline_renderable",
    "kind_for",
    "may_need_fallback",
]
