"""Splitting an article into embeddable chunks. Pure — no I/O, no clock,
no repository, so the rules are exhaustively testable in isolation (the
same constraint ``domain/policies.py`` and ``domain/rbac.py`` hold).

Why chunk at all: an embedding is a fixed-width summary of whatever text
it was given, so embedding a 4,000-word manual as one vector produces a
vector that is close to everything and useful for nothing. Retrieval
quality depends far more on chunk boundaries than on model choice.

Why *these* rules:

- **Split on structure first, length second.** A chunk that ends
  mid-sentence embeds the fragment, not the idea. Paragraph and heading
  boundaries are where an author already said "this is one thought".
- **Overlap.** A question whose answer straddles a boundary otherwise
  matches neither side well. The overlap is small enough not to inflate
  storage meaningfully and large enough to carry a sentence across.
- **Prefix the heading path.** ``"Refunds > Late deliveries"`` prepended
  to a chunk gives the embedding the context the author left implicit in
  the document structure, at near-zero cost. Without it, a chunk reading
  "within 14 days of receipt" is about nothing in particular.
- **Character counts, not tokens.** A real tokenizer is provider-specific
  and would put a vendor dependency in the domain layer. Characters are a
  stable proxy for a bound whose only job is to stay under a limit every
  provider sets far above it; ``token_estimate`` is reported separately
  and honestly named as an estimate.

The defaults suit multilingual text. Arabic carries more meaning per
character than English, so a character bound that is comfortable for
English is conservative for Arabic — which is the safe direction.
"""

import re
from dataclasses import dataclass

DEFAULT_MAX_CHARS = 1200
DEFAULT_OVERLAP_CHARS = 150
DEFAULT_MIN_CHARS = 80

# One or more blank lines, tolerating trailing spaces — the paragraph
# break in every format this platform ingests (plain text, Markdown, and
# the text extracted from an upload).
_PARAGRAPH_BREAK = re.compile(r"\n\s*\n+")
_MARKDOWN_HEADING = re.compile(r"^(#{1,6})\s+(.*\S)\s*$")
_WHITESPACE_RUN = re.compile(r"[ \t]+")


@dataclass(frozen=True)
class TextChunk:
    ordinal: int
    text: str
    heading_path: str | None

    @property
    def token_estimate(self) -> int:
        """Deliberately an estimate, and named as one.

        ~4 characters per token is a reasonable average for English and
        an over-estimate for Arabic. It exists for reporting and for cost
        projection, never as an input to a bound that must be exact.
        """
        return max(1, len(self.text) // 4)


def _normalise(text: str) -> str:
    """Collapses horizontal whitespace runs and strips trailing spaces
    per line, leaving vertical structure intact — paragraph breaks are
    load-bearing below, so they are exactly what is *not* collapsed."""
    lines = [
        _WHITESPACE_RUN.sub(" ", line).strip() for line in text.replace("\r\n", "\n").split("\n")
    ]
    return "\n".join(lines)


def _split_long_paragraph(paragraph: str, *, max_chars: int, overlap_chars: int) -> list[str]:
    """Splits one over-long paragraph on sentence boundaries where it can,
    and mid-text only where a single sentence exceeds the bound on its
    own. Sentence terminators include the Arabic question mark (``؟``)
    and full stop, so Arabic prose splits on sentences rather than being
    treated as one unbroken run."""
    if len(paragraph) <= max_chars:
        return [paragraph]

    sentences = re.split(r"(?<=[.!?؟。])\s+", paragraph)
    pieces: list[str] = []
    current = ""
    for sentence in sentences:
        if not sentence:
            continue
        if current and len(current) + 1 + len(sentence) > max_chars:
            pieces.append(current)
            # Carry the tail of the previous piece so a boundary does not
            # orphan the sentence that spans it.
            tail = current[-overlap_chars:] if overlap_chars else ""
            current = f"{tail} {sentence}".strip() if tail else sentence
        else:
            current = f"{current} {sentence}".strip() if current else sentence

        while len(current) > max_chars:
            # A single sentence longer than the bound: hard-split, which
            # is the only remaining option and is still better than
            # dropping it or emitting an over-length chunk a provider
            # would reject.
            pieces.append(current[:max_chars])
            current = current[max(0, max_chars - overlap_chars) :]

    if current:
        pieces.append(current)
    return pieces


def chunk_article(
    *,
    title: str,
    body: str,
    max_chars: int = DEFAULT_MAX_CHARS,
    overlap_chars: int = DEFAULT_OVERLAP_CHARS,
    min_chars: int = DEFAULT_MIN_CHARS,
) -> list[TextChunk]:
    """Splits an article into ordered chunks.

    The title is prepended to the heading path of every chunk, so a chunk
    lifted out of its article still carries what it is about — a chunk is
    retrieved on its own and must stand on its own.

    A short article produces exactly one chunk, and an article that is
    entirely whitespace produces none rather than one empty chunk: a
    zero-content vector is close to every query and is the single worst
    row a retrieval index can hold.
    """
    if max_chars <= 0:
        raise ValueError("max_chars must be positive")
    if overlap_chars < 0 or overlap_chars >= max_chars:
        raise ValueError("overlap_chars must be non-negative and smaller than max_chars")

    clean_title = _normalise(title).strip()
    normalised = _normalise(body).strip()
    if not normalised and not clean_title:
        return []

    heading_stack: list[str] = []
    chunks: list[TextChunk] = []
    ordinal = 0
    pending: list[str] = []
    pending_heading: str | None = _heading_path(clean_title, heading_stack)

    def flush() -> None:
        nonlocal ordinal, pending
        if not pending:
            return
        text = "\n\n".join(pending).strip()
        pending = []
        if not text:
            return
        chunks.append(TextChunk(ordinal=ordinal, text=text, heading_path=pending_heading))
        ordinal += 1

    for block in _PARAGRAPH_BREAK.split(normalised):
        block = block.strip()
        if not block:
            continue

        lines = block.split("\n")
        heading_match = _MARKDOWN_HEADING.match(lines[0]) if lines else None
        if heading_match is not None:
            flush()
            level = len(heading_match.group(1))
            heading_stack[level - 1 :] = [heading_match.group(2)]
            pending_heading = _heading_path(clean_title, heading_stack)
            remainder = "\n".join(lines[1:]).strip()
            if not remainder:
                continue
            block = remainder

        for piece in _split_long_paragraph(block, max_chars=max_chars, overlap_chars=overlap_chars):
            current_len = sum(len(p) + 2 for p in pending)
            if pending and current_len + len(piece) > max_chars:
                flush()
            pending.append(piece)

    flush()

    if not chunks and clean_title:
        # A title with no body is still worth indexing — an FAQ entry
        # whose question is the whole article is a real shape.
        chunks.append(
            TextChunk(ordinal=0, text=clean_title, heading_path=_heading_path(clean_title, []))
        )

    return _merge_runts(chunks, min_chars=min_chars, max_chars=max_chars)


def _heading_path(title: str, stack: list[str]) -> str | None:
    parts = [part for part in ([title] + stack) if part]
    return " > ".join(parts) if parts else None


def _merge_runts(chunks: list[TextChunk], *, min_chars: int, max_chars: int) -> list[TextChunk]:
    """Folds a trailing scrap into its predecessor.

    A 20-character final chunk ("Thanks for reading.") is a row that will
    be retrieved for queries it cannot answer, because a short text embeds
    close to a great many things. Merging is preferred to dropping so no
    content is silently lost.
    """
    if len(chunks) < 2:
        return chunks

    merged: list[TextChunk] = []
    for chunk in chunks:
        if (
            merged
            and len(chunk.text) < min_chars
            and len(merged[-1].text) + len(chunk.text) + 2 <= max_chars
            and merged[-1].heading_path == chunk.heading_path
        ):
            previous = merged.pop()
            merged.append(
                TextChunk(
                    ordinal=previous.ordinal,
                    text=f"{previous.text}\n\n{chunk.text}",
                    heading_path=previous.heading_path,
                )
            )
            continue
        merged.append(
            TextChunk(ordinal=len(merged), text=chunk.text, heading_path=chunk.heading_path)
        )

    return merged


def embeddable_text(chunk: TextChunk) -> str:
    """What actually gets embedded: the heading path, then the chunk.

    Kept here rather than in the service so that the exact string a
    ``content_hash`` is computed over and the exact string sent to the
    provider cannot drift apart — if they did, every chunk would look
    changed on every re-index and the incremental path would silently
    become a full one.
    """
    if chunk.heading_path:
        return f"{chunk.heading_path}\n\n{chunk.text}"
    return chunk.text
