"""Tier 0 and tier 1 feature extraction. Pure, and free.

See [the charter](../../../../docs/architecture/learning-platform-charter.md).

The design's cost model is a ladder where each tier escalates only what it
cannot settle:

| Tier | Cost | Phase |
|---|---|---|
| 0 — structural | free | **1** |
| 1 — lexical | negligible | **1** |
| 2 — embedding | cheap | 2 (needs clusters to place against) |
| 3 — small model | metered | 3 |
| 4 — strong model | expensive | per *candidate*, never per observation |

Phase 1 is tiers 0 and 1, and the point of that is not frugality for its
own sake: it means the platform can run over the whole corpus and measure
what extraction actually costs *before* anything metered is switched on.

Tier 2 is absent from phase 1 for a reason beyond scope. It exists to
place an observation against existing clusters, and there are none; and
the charter permits Learning to write only ``CLUSTER_CENTROID`` vectors
into the shared index, so an observation embedding has nowhere it is
allowed to live yet.

Everything here is deterministic. The same conversation produces the same
features on every run, which is what makes ``pipeline_version`` a
meaningful rollback boundary rather than a label on a moving target.
"""

from __future__ import annotations

import re
import unicodedata

from blinkengage.domain.learning_observation import (
    MAX_ENTITIES,
    MAX_TOPICS,
    Features,
)

#: Word-ish runs, Unicode-aware so Arabic tokenises like anything else.
_TOKEN = re.compile(r"\w+", re.UNICODE)

#: Things worth pulling out by shape rather than by meaning. Deliberately
#: conservative: a false positive here becomes a topic token that pollutes
#: every comparison downstream, and a missed one costs only a feature.
_ENTITY_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    # Order/invoice references: letters+digits, or long digit runs.
    ("ref", re.compile(r"\b(?:[A-Z]{2,}-?\d{3,}|\d{6,})\b")),
    ("email", re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.]+\b")),
    # Money with a currency marker on either side. JOD first because this
    # is a Jordan-based platform; the rest are what its customers see.
    ("money", re.compile(r"\b(?:JOD|USD|EUR|SAR|AED)\s?\d[\d,.]*|\d[\d,.]*\s?(?:JOD|USD|EUR)\b")),
    ("url", re.compile(r"https?://\S+")),
)

#: Tokens that carry no topical signal in any of the languages this
#: platform sees. Short and English/Arabic only — a large stop list is a
#: language model in disguise, and getting one wrong silently removes
#: meaning.
_STOPWORDS: frozenset[str] = frozenset(
    {
        "the",
        "and",
        "for",
        "you",
        "your",
        "our",
        "with",
        "this",
        "that",
        "have",
        "has",
        "had",
        "was",
        "were",
        "are",
        "is",
        "be",
        "been",
        "will",
        "would",
        "can",
        "could",
        "please",
        "thanks",
        "thank",
        "hello",
        "hi",
        "dear",
        "regards",
        "ok",
        "okay",
        "yes",
        "no",
        "من",
        "في",
        "على",
        "الى",
        "إلى",
        "عن",
        "مع",
        "هذا",
        "هذه",
        "ذلك",
        "التي",
        "الذي",
        "كان",
        "هل",
        "لا",
        "نعم",
        "شكرا",
        "مرحبا",
    }
)

#: Below this a token is noise; above it, an identifier we already caught
#: as an entity.
_MIN_TOPIC_TOKEN = 3
_MAX_TOPIC_TOKEN = 32

#: Arabic block. Language detection here is a *script* decision, not a
#: linguistic one — enough to route retrieval and to stratify, and honest
#: about being no more than that.
_ARABIC = re.compile(r"[؀-ۿݐ-ݿ]")
_LATIN = re.compile(r"[A-Za-z]")


def detect_language(text: str) -> str | None:
    """``ar``, ``en``, ``mixed``, or ``None`` when there is nothing to say.

    Script-based on purpose. A real language identifier is a model, and
    this feature's job is to stratify comparisons and hint retrieval — for
    which "is this Arabic" answers almost all of the value. ``mixed`` is a
    first-class answer rather than a tie-break, because Arabic/English
    code-switching in one message is normal traffic here, not an edge
    case, and collapsing it to whichever script won by one character
    would throw away the most interesting signal.
    """
    arabic = len(_ARABIC.findall(text))
    latin = len(_LATIN.findall(text))
    if arabic == 0 and latin == 0:
        return None
    if arabic and latin:
        weaker = min(arabic, latin)
        stronger = max(arabic, latin)
        if weaker / stronger >= 0.15:
            return "mixed"
    return "ar" if arabic > latin else "en"


def extract_entities(text: str) -> tuple[str, ...]:
    """Identifiers, by shape.

    Prefixed with their kind (``ref:4471``) so two different kinds sharing
    a value stay distinguishable, and so a later reader can filter without
    re-running the patterns.
    """
    found: list[str] = []
    seen: set[str] = set()
    for kind, pattern in _ENTITY_PATTERNS:
        for match in pattern.findall(text):
            value = f"{kind}:{match.strip()}"
            if value not in seen:
                seen.add(value)
                found.append(value)
            if len(found) >= MAX_ENTITIES:
                return tuple(found)
    return tuple(found)


def extract_topics(text: str) -> tuple[str, ...]:
    """The tokens most likely to say what this was about.

    Frequency-ranked, stop-worded, normalised. Not an intent — an intent
    is a tier-3 judgement and phase 1 makes none. These are the raw
    material a later stage clusters, and their job is to be *stable*: the
    same text must produce the same topics on every run, or
    ``pipeline_version`` stops meaning anything.
    """
    counts: dict[str, int] = {}
    for raw in _TOKEN.findall(unicodedata.normalize("NFKC", text).casefold()):
        if not (_MIN_TOPIC_TOKEN <= len(raw) <= _MAX_TOPIC_TOKEN):
            continue
        if raw in _STOPWORDS or raw.isdigit():
            continue
        counts[raw] = counts.get(raw, 0) + 1

    # Frequency first, then alphabetically — a deterministic tie-break, so
    # two runs over the same text cannot disagree.
    ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    return tuple(token for token, _count in ranked[:MAX_TOPICS])


def extract(
    *,
    human_text: str,
    inbound_turns: int,
    outbound_turns: int,
) -> Features:
    """Tier 0 + tier 1, from human-authored text only.

    **Only human text reaches this.** Machine-written content is filtered
    out by the assembler before extraction, not filtered from the results
    afterwards — otherwise a conversation Autopilot answered would
    contribute the platform's own vocabulary to the topics it later
    clusters on, which is the feedback loop wearing a different hat.
    """
    return Features(
        language=detect_language(human_text),
        topics=extract_topics(human_text),
        entities=extract_entities(human_text),
        inbound_turns=inbound_turns,
        outbound_turns=outbound_turns,
        human_char_count=len(human_text.strip()),
    )


__all__ = ["detect_language", "extract", "extract_entities", "extract_topics"]
