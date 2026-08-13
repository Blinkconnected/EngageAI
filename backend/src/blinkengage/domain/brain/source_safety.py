"""Source material is data. Two rules, both narrow, both structural.

**Credentials are refused, never redacted.** A message carrying a private key
or a bearer token is refused entry and audited. Redacting and continuing looks
tidier and fails open: a pattern that misses leaves the secret in a row that
retrieval can read, and "we filtered it" is a claim nobody can verify after the
fact. Refusing is verifiable — the row does not exist.

This is deliberately **not** a DLP engine. It looks for material that is
unmistakably a credential and nothing else. Detecting PII, or guessing that a
number might be a card, is a different product with a different false-positive
budget, and a company's own price list is exactly the kind of document a
nervous heuristic would reject.

**HTML is flattened, never rendered.** The derived plain text is for reading
and later extraction; the original body is kept verbatim as evidence. Nothing
here fetches a remote image, follows a link, or executes anything — there is no
HTTP client in this module and no way to reach one from it.
"""

from __future__ import annotations

import re

#: Patterns that are credential material and essentially nothing else.
#:
#: Each one had to be unambiguous to earn its place. ``password:`` is *not*
#: here: "the password reset email says..." is ordinary support prose, and a
#: rule that refuses a company's own documentation about passwords is a rule
#: that gets switched off. PEM blocks, assigned API keys and bearer tokens are
#: not prose in any document a company means to teach from.
_CREDENTIAL_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"\bapi[_-]?key\s*[:=]\s*\S{12,}", re.IGNORECASE),
    re.compile(r"\bsecret[_-]?key\s*[:=]\s*\S{12,}", re.IGNORECASE),
    re.compile(r"\bAuthorization\s*:\s*Bearer\s+\S{16,}", re.IGNORECASE),
    re.compile(r"\baws_secret_access_key\s*[:=]\s*\S{16,}", re.IGNORECASE),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}"),
)

_SCRIPT_OR_STYLE = re.compile(r"<(script|style)\b.*?</\1>", re.IGNORECASE | re.DOTALL)
_TAG = re.compile(r"<[^>]+>")
_WHITESPACE = re.compile(r"[ \t\r\f\v]+")
_BLANK_LINES = re.compile(r"\n{3,}")


def contains_credential_material(*texts: str | None) -> bool:
    """Does any of this look like a secret rather than company knowledge?"""
    for text in texts:
        if not text:
            continue
        if any(pattern.search(text) for pattern in _CREDENTIAL_PATTERNS):
            return True
    return False


def to_plain_text(html: str) -> str:
    """A readable flattening of an HTML body.

    Script and style *contents* are dropped rather than unwrapped — leaving
    the body of a ``<script>`` in the text would put executable-looking source
    into a field a model later reads, which is the shape of an injection even
    when nothing executes it.

    Nothing is fetched. ``<img src>`` never becomes a request, and a link's
    target is discarded with the tag; this returns what a person would read,
    not what a browser would load.
    """
    without_blocks = _SCRIPT_OR_STYLE.sub(" ", html)
    without_tags = _TAG.sub(" ", without_blocks)
    unescaped = (
        without_tags.replace("&nbsp;", " ")
        .replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&quot;", '"')
        .replace("&#39;", "'")
    )
    collapsed = _WHITESPACE.sub(" ", unescaped)
    return _BLANK_LINES.sub("\n\n", collapsed).strip()


__all__ = ["contains_credential_material", "to_plain_text"]
