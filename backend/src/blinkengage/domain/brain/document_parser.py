"""The seam OCR will attach to, named now so it cannot expand this phase.

A parser is resolved by *kind*, never by filename and never by a chain of
``if`` statements at the call site. That is the whole architectural point: a
scanned PDF is currently refused with ``NO_TEXT_LAYER``, and the day an OCR
parser exists it registers itself for that case and the ingestion pipeline does
not change. Naming the extension point is what stops OCR being argued into the
current milestone.

The protocol lives in the domain and every implementation lives in
infrastructure, because reading a PDF means a third-party library and the rules
about what may be read must not.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from blinkengage.domain.brain.documents import DocumentKind


@dataclass(frozen=True, slots=True)
class ExtractedDocument:
    """Text, and enough about how it was obtained to reproduce or distrust it.

    ``parser_version`` is not decoration. Extraction quality changes with the
    library, so a record citing this text needs to say which parser produced
    it — otherwise "the document says 180" is unfalsifiable a year later when
    the same file extracts differently.
    """

    text: str
    parser: str
    parser_version: str
    #: Pages, sheets or rows actually read. Records a truncation that would
    #: otherwise be invisible in the text.
    units_read: int = 0
    #: True when a cap stopped the read before the document ended.
    truncated: bool = False
    metadata: dict[str, str] = field(default_factory=dict)


class DocumentParser(Protocol):
    """Bytes in, text out, or a ``DocumentRejected`` with a stated reason.

    Implementations must not touch the network, must not execute embedded
    code, and must apply their own resource caps — the generic size and
    archive checks run first, but only the parser knows what a page is.
    """

    @property
    def kind(self) -> DocumentKind: ...

    @property
    def name(self) -> str: ...

    def extract(self, data: bytes) -> ExtractedDocument: ...


__all__ = ["DocumentParser", "ExtractedDocument"]
