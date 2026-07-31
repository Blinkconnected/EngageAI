"""Which font an invoice is set in, and what happens to a glyph it lacks.

A rendered invoice is the one artefact in this product that a customer files,
prints and pays against. It carries their **legal name**, and there is exactly
one unacceptable way to render that: as a row of solid black rectangles.

That is what happens by default. ReportLab's base-14 fonts — Helvetica among
them — are Latin-1, and a Jordanian company name in Arabic comes out as one
filled box per character. On paper it reads as a redaction or a corrupted
file. The customer cannot tell which, and neither can the person who posted it.

So this module does two things:

**It ships a Unicode font.** DejaVu Sans is vendored beside this module and
used for every invoice. It covers Latin, Arabic — including all 141 Arabic
Presentation Forms, which is what lets ``arabic.shape`` join letters properly —
Cyrillic and Greek. Its licence (Bitstream Vera, plus public-domain DejaVu
changes) permits embedding in documents an installation sends to its own
customers, which is exactly what an invoice is. It is vendored rather than
assumed present because an invoice that renders differently depending on which
fonts a host happens to have installed is not a document anybody can rely on.

An installation that wants its own face can point ``BILLING_DOCUMENT_FONT`` at
one, and it takes precedence.

**Nothing ever prints a box.** If a face somehow cannot represent a character —
a customer name in a script the configured font lacks — the text falls back to
the company's ASCII slug rather than to a row of filled rectangles, which on
paper reads as a redaction or a corrupted file. The substitution is logged so
it is discoverable rather than mysterious.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from reportlab.lib.fonts import addMapping
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

from blinkengage.core.logging import get_logger

logger = get_logger(__name__)

#: Where an installation says which font to use. One variable, pointing at a
#: regular weight; a bold sibling beside it is used when it exists.
FONT_ENV_VAR = "BILLING_DOCUMENT_FONT"

#: Paths worth trying before giving up, so a host that already has a suitable
#: font needs no configuration at all. Ordered by Arabic coverage.
_BUNDLED = str(Path(__file__).with_name("assets") / "DejaVuSans.ttf")

_WELL_KNOWN = (
    _BUNDLED,
    "/usr/share/fonts/truetype/noto/NotoSansArabic-Regular.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
)

#: The names the renderer asks for. They resolve to a Unicode face when one
#: was registered and to Helvetica when none was, so the renderer never has to
#: know which happened.
REGULAR = "InvoiceText"
BOLD = "InvoiceText-Bold"

_FALLBACK_REGULAR = "Helvetica"
_FALLBACK_BOLD = "Helvetica-Bold"


@dataclass(frozen=True, slots=True)
class DocumentFont:
    """The face invoices are set in, and what it can actually print."""

    regular: str
    bold: str
    #: Every codepoint the face can render. Empty for the base-14 fallback,
    #: where coverage is "Latin-1" and is checked by range instead.
    coverage: frozenset[int]
    #: True when a real Unicode face was found. False means Latin-1 only, and
    #: that non-Latin names will be substituted rather than printed.
    unicode_capable: bool

    def can_render(self, text: str) -> bool:
        if self.unicode_capable:
            return all(ord(ch) in self.coverage or ch.isspace() for ch in text)
        # Latin-1 is what the base-14 fonts encode. Anything above it is a
        # box, which is the outcome this module exists to prevent.
        return all(ord(ch) < 0x100 for ch in text)


def _candidates() -> tuple[str, ...]:
    configured = os.environ.get(FONT_ENV_VAR, "").strip()
    return (configured, *_WELL_KNOWN) if configured else _WELL_KNOWN


def _coverage(path: str) -> frozenset[int]:
    """Every codepoint the file maps.

    Read from the font's own cmap through reportlab, which has already
    parsed it — so this costs nothing beyond the registration that was
    happening anyway, and cannot disagree with what will actually print.
    """
    face = pdfmetrics.getFont(_registered_name(path)).face
    return frozenset(getattr(face, "charToGlyph", {}))


def _registered_name(path: str) -> str:
    return f"invoice-{Path(path).stem}"


def _register(path: str) -> DocumentFont | None:
    """Registers one file, or returns ``None`` if it cannot be used.

    Never raises. A malformed or unreadable font must degrade to the
    fallback, because the alternative is an invoice that cannot be produced
    at all — and a customer who cannot get their bill is a worse outcome
    than one whose bill is set in Helvetica.
    """
    if not path or not Path(path).is_file():
        return None
    try:
        name = _registered_name(path)
        pdfmetrics.registerFont(TTFont(name, path))
        bold_path = _bold_beside(path)
        bold_name = name
        if bold_path is not None:
            bold_name = f"{name}-Bold"
            pdfmetrics.registerFont(TTFont(bold_name, str(bold_path)))
        # Registered under the names the renderer asks for, so the styles do
        # not have to branch on which file was found.
        pdfmetrics.registerFont(TTFont(REGULAR, path))
        pdfmetrics.registerFont(TTFont(BOLD, str(bold_path) if bold_path else path))
        addMapping(REGULAR, 0, 0, REGULAR)
        addMapping(REGULAR, 1, 0, BOLD)
        coverage = _coverage(path)
    except Exception as error:  # noqa: BLE001 — see the docstring.
        logger.warning("invoice_font.unusable", path=path, error=str(error))
        return None
    logger.info(
        "invoice_font.registered",
        path=path,
        bold=str(bold_path) if bold_path else None,
        codepoints=len(coverage),
        arabic=sum(1 for c in coverage if 0x0600 <= c <= 0x06FF),
    )
    return DocumentFont(regular=REGULAR, bold=BOLD, coverage=coverage, unicode_capable=True)


def _bold_beside(path: str) -> Path | None:
    """The bold weight sitting next to a regular one, by the usual names."""
    stem = Path(path)
    for pattern in ("-Bold", "Bold", "-bold"):
        for candidate in (
            stem.with_name(stem.stem.replace("-Regular", pattern) + stem.suffix),
            stem.with_name(stem.stem + pattern + stem.suffix),
        ):
            if candidate.is_file() and candidate != stem:
                return candidate
    return None


_resolved: DocumentFont | None = None


def document_font() -> DocumentFont:
    """The face this installation sets invoices in. Resolved once."""
    global _resolved
    if _resolved is None:
        for path in _candidates():
            found = _register(path)
            if found is not None:
                _resolved = found
                break
        else:
            logger.info("invoice_font.fallback", reason="no unicode font found")
            _resolved = DocumentFont(
                regular=_FALLBACK_REGULAR,
                bold=_FALLBACK_BOLD,
                coverage=frozenset(),
                unicode_capable=False,
            )
    return _resolved


def printable(text: str, *, fallback: str = "", field: str = "text") -> str:
    """``text`` if the font can print it, otherwise something readable.

    The rule this module exists for. A customer's legal name that the active
    font cannot represent becomes their slug — an identifier already on the
    document, in ASCII, that a person can read aloud — rather than a row of
    filled rectangles that reads as a redaction.

    A caller with no fallback to offer gets the characters the font *can*
    print, with the rest dropped. Still not the name, but still not a bar.
    """
    font = document_font()
    if not text or font.can_render(text):
        return text
    logger.warning(
        "invoice_font.substituted",
        field=field,
        reason="the configured font cannot render this text",
        used_fallback=bool(fallback),
    )
    if fallback and font.can_render(fallback):
        return fallback
    stripped = "".join(ch for ch in text if font.can_render(ch)).strip()
    return stripped or fallback or "—"


def reset_for_tests() -> None:
    """Forgets the resolved face. Only tests should need this."""
    global _resolved
    _resolved = None


__all__ = [
    "BOLD",
    "FONT_ENV_VAR",
    "REGULAR",
    "DocumentFont",
    "document_font",
    "printable",
    "reset_for_tests",
]
