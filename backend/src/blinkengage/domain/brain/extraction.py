"""What a model may return, and what is thrown away before it counts.

The model's output is the least trustworthy input in this system: it is
generated from a document a stranger wrote, by a component with no stake in
being right. So this module's job is subtraction. A fact survives only if it
carries a verbatim passage, names a known record type, and passes the same
attribute validation a human-authored record passes.

Two rules that are not negotiable and are enforced here rather than requested
of the model:

**The subject key is computed, never supplied.** ``canonical_subject_key`` is
deterministic; a model-generated key is not, and a key that differs between two
runs forks one product's history into two chains no query joins back together.

**A fact without its passage is discarded.** The passage is the reviewer's only
way to check 195 against the sentence it came from. Without it a hallucination
and a correct reading are the same object.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from blinkengage.domain.knowledge_records import (
    KnowledgeRecordType,
    canonical_subject_key,
)


class ConfidenceTier(StrEnum):
    """How sure the extractor claims to be.

    Tiers, not a float. A number implies a calibration nobody has measured, and
    a threshold on an uncalibrated number is a decision dressed as arithmetic.

    Tiers order a review queue. They never affect authority: a HIGH price is a
    DRAFT exactly like a LOW one.
    """

    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class ExtractionFailure(StrEnum):
    """Why extraction produced nothing usable."""

    #: The model returned something this code cannot read. Retryable: the next
    #: attempt may parse.
    UNPARSEABLE_OUTPUT = "UNPARSEABLE_OUTPUT"
    #: Facts were returned and every one failed validation. Terminal — the
    #: same document will fail the same way.
    EXTRACTION_INVALID = "EXTRACTION_INVALID"
    #: Nothing to read.
    EMPTY_DOCUMENT = "EMPTY_DOCUMENT"
    #: Provider error. Retryable.
    PROVIDER_ERROR = "PROVIDER_ERROR"


class InvalidExtractedFact(Exception):
    """One fact was discarded. Never fatal on its own."""


@dataclass(frozen=True, slots=True)
class ExtractedFact:
    """One candidate, already validated. Not yet knowledge of any kind."""

    record_type: KnowledgeRecordType
    subject_label: str
    attributes: Mapping[str, str]
    source_passage: str
    confidence: ConfidenceTier
    effective_from: datetime | None = None
    effective_until: datetime | None = None

    @property
    def subject_key(self) -> str:
        """Derived, always. Never whatever the model called it."""
        return canonical_subject_key(self.subject_label)


@dataclass(frozen=True, slots=True)
class ExtractionResult:
    """Everything one document yielded, including what it cost to find out."""

    facts: tuple[ExtractedFact, ...] = ()
    #: Candidates the model returned that failed validation. Counted rather
    #: than discarded silently: a document where nine of ten facts were
    #: rejected is a document somebody should look at.
    rejected_count: int = 0
    extractor_version: str = ""
    model_identifier: str = ""
    failure: ExtractionFailure | None = None

    @property
    def produced_nothing(self) -> bool:
        return not self.facts

    @property
    def all_invalid(self) -> bool:
        """Facts were offered and none survived. Terminal, not transient."""
        return not self.facts and self.rejected_count > 0


#: Keys a model may not set. Authority, identity and lifecycle are decided by
#: this platform; a document that names them is a document trying to promote
#: itself, and the value is dropped rather than argued with.
FORBIDDEN_ATTRIBUTE_KEYS: frozenset[str] = frozenset(
    {
        "lifecycle_state",
        "access_level",
        "approved_by_user_id",
        "approved_at",
        "company_id",
        "created_from",
        "subject_key",
        "version",
    }
)


def sanitise_attributes(raw: Mapping[str, object]) -> dict[str, str]:
    """Strings only, and none of the keys that would grant standing.

    Values are stringified because the attribute schemas store text and
    compare it; a nested object from a model is not a value this system has a
    meaning for.
    """
    return {
        str(key): str(value)
        for key, value in raw.items()
        if str(key) not in FORBIDDEN_ATTRIBUTE_KEYS and value is not None
    }


def build_fact(
    *,
    record_type: str,
    subject_label: str,
    attributes: Mapping[str, object],
    source_passage: str,
    confidence: str,
    effective_from: datetime | None = None,
    effective_until: datetime | None = None,
) -> ExtractedFact:
    """One candidate, or :class:`InvalidExtractedFact`.

    Every rejection here is a fact that does not reach a reviewer, which is the
    intended direction: a queue full of unusable drafts is a queue nobody
    works.
    """
    if not source_passage or not source_passage.strip():
        raise InvalidExtractedFact("a fact without its source passage is not evidence")
    if not subject_label or not subject_label.strip():
        raise InvalidExtractedFact("no subject")

    try:
        kind = KnowledgeRecordType(record_type)
    except ValueError as exc:
        raise InvalidExtractedFact(f"unknown record type {record_type!r}") from exc

    try:
        tier = ConfidenceTier(str(confidence).upper())
    except ValueError:
        # An unrecognised tier reads as the lowest, never the highest: a model
        # inventing a confidence label must not thereby claim certainty.
        tier = ConfidenceTier.LOW

    cleaned = sanitise_attributes(attributes)
    if not cleaned:
        raise InvalidExtractedFact("no usable attributes")

    fact = ExtractedFact(
        record_type=kind,
        subject_label=subject_label.strip(),
        attributes=cleaned,
        source_passage=source_passage.strip(),
        confidence=tier,
        effective_from=effective_from,
        effective_until=effective_until,
    )
    # Derivable key or no fact: a label with no letters or digits cannot be
    # looked up later, so storing it would create a record nothing can find.
    try:
        _ = fact.subject_key
    except Exception as exc:  # noqa: BLE001
        raise InvalidExtractedFact(f"subject key not derivable: {exc}") from exc
    return fact


__all__ = [
    "FORBIDDEN_ATTRIBUTE_KEYS",
    "ConfidenceTier",
    "ExtractedFact",
    "ExtractionFailure",
    "ExtractionResult",
    "InvalidExtractedFact",
    "build_fact",
    "sanitise_attributes",
]
