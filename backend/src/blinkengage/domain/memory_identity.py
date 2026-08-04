"""What makes two observations the *same* fact.

Pure. This is the deduplication rule, and it decides whether the platform
accumulates evidence or accumulates duplicates.

Getting it wrong is quiet in both directions. Too strict, and "prefers
Arabic" and "Prefers  arabic" become two facts, each with half the
support, neither ever crossing a threshold — the platform observes
something a hundred times and believes nothing. Too loose, and two
genuinely different facts merge into one whose statement describes neither.

The key is deliberately **not** the statement text. A statement is prose
that a component may reword between runs; keying on it would fork a fact's
history every time the wording changed, which is the same failure the
customer-context fingerprint avoids by hashing routing-relevant attributes
rather than the whole record.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata

#: Arabic diacritics (tashkeel). Optional in writing, semantically empty,
#: and present or absent depending on who typed it — so a key that kept
#: them would treat "مرحبا" and "مَرْحَبا" as different facts.
_ARABIC_DIACRITICS = re.compile(r"[ؐ-ًؚ-ٰٟۖ-ۜ۟-۪ۨ-ۭ]")
_NON_KEY_CHARS = re.compile(r"[^\w\s]", re.UNICODE)
_WHITESPACE = re.compile(r"\s+")

#: Arabic letters with orthographic variants that carry no meaning
#: difference in the contexts this platform sees. Normalised so a key does
#: not depend on which keyboard somebody used.
_ARABIC_FOLD = str.maketrans(
    {
        "أ": "ا",
        "إ": "ا",
        "آ": "ا",
        "ٱ": "ا",
        "ى": "ي",
        "ة": "ه",
        "ؤ": "و",
        "ئ": "ي",
    }
)

#: Keys are hashed past this length rather than truncated. Truncation makes
#: two long, distinct keys collide on their shared prefix — and long keys
#: are exactly the descriptive ones where that prefix is most likely shared.
MAX_KEY_LENGTH = 180


def normalise_key(raw: str) -> str:
    """The canonical form of a fact key.

    Unicode NFKC first, so visually identical characters from different
    code points fold together before anything else looks at them.
    """
    folded = unicodedata.normalize("NFKC", raw).strip().casefold()
    folded = _ARABIC_DIACRITICS.sub("", folded)
    folded = folded.translate(_ARABIC_FOLD)
    folded = _NON_KEY_CHARS.sub(" ", folded)
    folded = _WHITESPACE.sub(" ", folded).strip()

    if not folded:
        # An empty key would make every empty-keyed fact of a type collide
        # into one row. A stable sentinel keeps them separable by type
        # while still being deterministic.
        return "_"

    if len(folded) > MAX_KEY_LENGTH:
        digest = hashlib.sha256(folded.encode("utf-8")).hexdigest()[:32]
        return f"{folded[: MAX_KEY_LENGTH - 33]}#{digest}"
    return folded


def stratum_key(stratum: dict[str, object] | None) -> str:
    """The canonical form of an Experience stratum.

    Experience facts are compared *within* a stratum — customer tier,
    intent, channel, language — never pooled across them, because pooling
    is how an approach that wins in every segment loses overall. So the
    stratum is part of the fact's identity: the same claim about two
    different segments is two facts, and merging them would reintroduce
    the confounding the stratification exists to remove.

    Canonically ordered, so ``{"tier": "vip", "channel": "whatsapp"}`` and
    ``{"channel": "whatsapp", "tier": "vip"}`` are one stratum and not two.
    """
    if not stratum:
        return ""
    parts = [f"{key}={normalise_key(str(value))}" for key, value in sorted(stratum.items())]
    return "|".join(parts)


def fact_key(*, topic: str, stratum: dict[str, object] | None = None) -> str:
    """The full dedupe key for a fact within its (tier, subject, type)."""
    base = normalise_key(topic)
    suffix = stratum_key(stratum)
    if not suffix:
        return base
    combined = f"{base}::{suffix}"
    if len(combined) > MAX_KEY_LENGTH:
        digest = hashlib.sha256(combined.encode("utf-8")).hexdigest()[:32]
        return f"{combined[: MAX_KEY_LENGTH - 33]}#{digest}"
    return combined


__all__ = ["MAX_KEY_LENGTH", "fact_key", "normalise_key", "stratum_key"]
