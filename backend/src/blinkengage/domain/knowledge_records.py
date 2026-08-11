"""Structured knowledge: the facts a company looks *up* rather than reads.

See ``docs/architecture/company-knowledge-and-voice.md``.

Pure: no I/O, no clock, no repository — the same constraint
``domain/chunking.py``, ``domain/faq.py`` and ``domain/memory.py`` hold. The
canonical key in particular *must* be derivable without a database, because
a key that consulted the current state of the store would compute
differently before and after a write.

**Why this is not a knowledge article.** An article is prose for a human,
found by resemblance. "What is the price of DIA 500 Mbps?" answered by
cosine similarity is a lookup answered by resemblance, and resemblance
returns the 200 Mbps row with a respectable score. A price is a value for a
machine, found by identity.

**Why this is not a memory fact.** ``memory_facts`` is evidential:
confidence computed from a support stream, lifecycle driven by decay and
contradiction. A price has no confidence. It is 180 JOD because a human
approved a document saying so. Storing an approved price in a table whose
semantics are *this decays unless re-observed* would make the platform's
most auditable statement its least stable one.

The two stay connected without either writing the other: a record may cite
a document version, and Memory may observe that a record is asked about
often.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Any

from blinkengage.domain.exceptions import DomainError

# --------------------------------------------------------------------------
# Vocabulary
# --------------------------------------------------------------------------


class KnowledgeRecordType(StrEnum):
    """What kind of structured fact a record holds.

    Each type owns an ``attributes`` schema (see ``ATTRIBUTE_SCHEMAS``) and
    a risk classification (see ``SENSITIVE_RECORD_TYPES``). Adding a type is
    adding both, deliberately — a type with no schema stores whatever it is
    given, and a type with no risk classification defaults to the safe side
    only if somebody remembered to say so.
    """

    PRICE = "PRICE"
    PRODUCT = "PRODUCT"
    SERVICE = "SERVICE"
    SLA_TERM = "SLA_TERM"
    POLICY_PARAM = "POLICY_PARAM"


#: Types that always require human review before publication, whatever the
#: sender's trust level and whatever an extraction's confidence.
#:
#: This is a floor, not a default. Configuration may make a low-risk type
#: stricter; nothing may make one of these looser. A trusted sender is a
#: statement about a mailbox, and mailboxes are compromised.
#:
#: M2A does not implement ingestion, so nothing consults this yet. It is
#: declared here because the classification belongs with the type it
#: describes, not with the pipeline that will later read it.
SENSITIVE_RECORD_TYPES: frozenset[KnowledgeRecordType] = frozenset(
    {
        KnowledgeRecordType.PRICE,
        KnowledgeRecordType.SLA_TERM,
        KnowledgeRecordType.POLICY_PARAM,
    }
)


class KnowledgeLifecycleState(StrEnum):
    """Where a record sits between drafted and withdrawn.

    There is deliberately no ``DELETED``. A price that was quoted must be
    reproducible in an audit two years later, which is the founding argument
    of the Company Intelligence Engine. Withdrawal is ``ARCHIVED``;
    replacement is ``SUPERSEDED``; neither loses the row.
    """

    #: Created but not authoritative. Never answers a question.
    DRAFT = "DRAFT"
    #: The current truth for this subject over this period.
    ACTIVE = "ACTIVE"
    #: Replaced by a newer version. Still the correct answer to "what did
    #: we quote in July".
    SUPERSEDED = "SUPERSEDED"
    #: Withdrawn. Not authoritative, not deleted.
    ARCHIVED = "ARCHIVED"


#: States a record may answer from.
#:
#: ``SUPERSEDED`` is included, and the reason is not history-keeping — it is
#: correctness *today*. Supersession closes the outgoing period at the
#: incoming record's ``effective_from``, so a price change scheduled for
#: next month leaves the current record ``SUPERSEDED`` immediately while its
#: replacement does not yet cover today. Resolving only ``ACTIVE`` would
#: answer "what does this cost?" with nothing for a month, because somebody
#: scheduled a change.
#:
#: It is safe because periods among these two states are disjoint by
#: construction: the overlap rule keeps ``ACTIVE`` records apart, and
#: supersession closes the old period exactly where the new one opens.
#:
#: ``DRAFT`` and ``ARCHIVED`` are excluded and must stay excluded. A draft
#: was never true, and an archived record was withdrawn — its period is left
#: intact precisely so the audit trail keeps it, which means an archived
#: record *can* overlap a later active one and could reintroduce the
#: ambiguity this module exists to prevent.
RESOLVABLE_STATES: frozenset[KnowledgeLifecycleState] = frozenset(
    {KnowledgeLifecycleState.ACTIVE, KnowledgeLifecycleState.SUPERSEDED}
)


class KnowledgeAccessLevel(StrEnum):
    """Who a record may be shown to.

    Enforced at *retrieval* by audience, never at generation. Enforcing at
    generation would mean the restricted text was in the context and one
    prompt away from disclosure; enforcing at retrieval means it was never
    fetched.
    """

    #: May be retrieved for a customer-facing answer.
    PUBLIC_TO_AI = "PUBLIC_TO_AI"
    #: May influence a reply as a constraint, but is never quoted or cited.
    INTERNAL = "INTERNAL"
    #: Requires ``knowledge.approve_restricted`` to publish, and is never
    #: retrieved for a customer-facing answer.
    RESTRICTED = "RESTRICTED"


class KnowledgeRecordError(DomainError):
    """Base for every structured-knowledge rule."""


class SubjectLabelRequiredError(KnowledgeRecordError):
    def __init__(self) -> None:
        super().__init__("A knowledge record needs a subject label.")


class SubjectKeyNotDerivableError(KnowledgeRecordError):
    """The label normalised away to nothing.

    A label of punctuation and whitespace has no canonical form, and
    inventing one (a hash, a uuid) would produce a key nobody can look up
    and nobody chose.
    """

    def __init__(self, label: str) -> None:
        super().__init__(
            f"No canonical key can be derived from {label!r}: it normalises to "
            "an empty string. A subject needs at least one letter or digit."
        )


class EffectivePeriodError(KnowledgeRecordError):
    def __init__(self, message: str) -> None:
        super().__init__(message)


class OverlappingRecordError(KnowledgeRecordError):
    """Two active records claim the same subject at the same moment.

    Never resolved by picking one. Two overlapping active prices is a data
    problem the platform must surface; a layer that silently returned the
    better-scoring one would convert a data problem into a quotation.
    """

    def __init__(self, subject_key: str, record_type: str) -> None:
        super().__init__(
            f"Another active {record_type} record for {subject_key!r} already covers "
            "part of this period. Supersede it instead of adding a second one."
        )


class AttributeSchemaError(KnowledgeRecordError):
    def __init__(self, message: str) -> None:
        super().__init__(message)


class ProvenanceRequiredError(KnowledgeRecordError):
    """Publishing without a traceable origin.

    Provenance is not optional on an authoritative fact: an approved price
    whose source nobody recorded is a number the platform cannot defend in
    the audit it exists for.
    """

    def __init__(self) -> None:
        super().__init__(
            "A record cannot be published without provenance: it needs a source "
            "document version or a source reference."
        )


class InvalidLifecycleTransitionError(KnowledgeRecordError):
    def __init__(self, current: str, target: str) -> None:
        super().__init__(f"A {current} record cannot become {target}.")


# --------------------------------------------------------------------------
# Canonical subject key
# --------------------------------------------------------------------------

#: Cap on the stored key. Long enough for a real product name in either
#: script, short enough to index.
MAX_SUBJECT_KEY_CHARS = 200
MAX_SUBJECT_LABEL_CHARS = 300

#: Arabic diacritics (harakat, tanwin, shadda, sukun) and the tatweel
#: elongation character. All are presentational: ``الخِدمة`` and ``الخدمة``
#: are the same word, and a customer types whichever their keyboard offers.
_ARABIC_DIACRITICS = re.compile(r"[ؐ-ًؚ-ٰٟۖ-ۭـ]")

#: Orthographic variants that are the same letter in practice. Arabic
#: writers alternate between these freely and search engines that do not
#: fold them return nothing for the other spelling.
_ARABIC_FOLDING = str.maketrans(
    {
        "أ": "ا",  # أ alef with hamza above  → ا
        "إ": "ا",  # إ alef with hamza below  → ا
        "آ": "ا",  # آ alef with madda        → ا
        "ٱ": "ا",  # ٱ alef wasla             → ا
        "ى": "ي",  # ى alef maksura           → ي
        "ة": "ه",  # ة teh marbuta            → ه
    }
)


def _fold_digits(text: str) -> str:
    """Arabic-Indic and other non-ASCII digits to ASCII.

    NFKC does **not** do this — ``٥`` is a distinct digit character, not a
    compatibility form of ``5``, so it survives normalisation unchanged.
    Verified rather than assumed: ``unicodedata.normalize("NFKC", "٥")``
    returns ``"٥"``.

    That matters here because Arabic keyboards produce these routinely, and
    without folding ``خدمة ٥٠٠`` and ``خدمة 500`` are two products with two
    price histories. ``unicodedata.digit`` covers every script's digits
    rather than just the Arabic ones, so Persian ``۵`` folds too.
    """
    if text.isascii():
        return text
    return "".join(
        str(unicodedata.digit(ch)) if not ch.isascii() and ch.isdigit() else ch for ch in text
    )


#: Anything that is not a letter, a digit or a mark becomes a separator.
#: Marks survive step 1 only to be removed by the Arabic fold; keeping the
#: class here means a stray combining character does not split a token.
_NON_TOKEN = re.compile(r"[^\w]+", re.UNICODE)
_UNDERSCORE_RUN = re.compile(r"_+")
_SEPARATOR_RUN = re.compile(r"-+")


def canonical_subject_key(label: str) -> str:
    """The deterministic identity of a subject, derived from its label.

    Pure and total: the same label yields the same key in 2026 and in 2029,
    on any machine, in any process. Nothing here reads the database, the
    clock, the current version or a model.

    **No model generates this.** An LLM-produced key is not reproducible,
    and a key that differs between two runs silently forks one product's
    history into two chains that no query joins back together.

    The order of operations is load-bearing:

    1. **NFKC** collapses compatibility forms — full-width Latin becomes
       ASCII, ligatures decompose. Done first so every later step sees one
       representation.
    2. **Digit folding** maps Arabic-Indic ``٥`` and friends to ``5``. NFKC
       does *not* do this (see ``_fold_digits``), and Arabic keyboards
       produce these constantly.
    3. **Arabic folding** removes diacritics and tatweel, then unifies alef
       forms, alef maksura and teh marbuta. Without it ``الخدمة`` and
       ``الخدمه`` are different products, and both spellings occur in real
       traffic.
    4. **Case folding** via ``casefold``, not ``lower`` — correct for
       non-ASCII, where ``lower`` is not.
    5. **Tokenisation**: anything that is not a letter or digit becomes a
       separator, so ``DIA/500`` and ``DIA 500`` agree.
    6. **Collapse and trim** so no key begins, ends or doubles a separator.

    ``DIA 500 Mbps`` → ``dia-500-mbps``
    ``  DIA/500  Mbps  `` → ``dia-500-mbps``
    ``خدمة ٥٠٠`` → ``خدمه-500``

    Raises ``SubjectKeyNotDerivableError`` when a label carries no letter or
    digit at all, rather than inventing a key from a hash.
    """
    if not label or not label.strip():
        raise SubjectLabelRequiredError

    text = unicodedata.normalize("NFKC", label)
    text = _fold_digits(text)
    text = _ARABIC_DIACRITICS.sub("", text)
    text = text.translate(_ARABIC_FOLDING)
    text = text.casefold()

    # ``\w`` keeps underscore, which is punctuation for our purposes.
    text = _NON_TOKEN.sub("-", text)
    text = _UNDERSCORE_RUN.sub("-", text)
    text = _SEPARATOR_RUN.sub("-", text).strip("-")

    if not text:
        raise SubjectKeyNotDerivableError(label)

    if len(text) > MAX_SUBJECT_KEY_CHARS:
        text = text[:MAX_SUBJECT_KEY_CHARS].rstrip("-")
        # Truncation cannot empty the string: the first character survived
        # the checks above and is not a separator.

    return text


def normalise_subject_label(label: str) -> str:
    """The authored form, whitespace-tidied but otherwise left alone.

    The key is for lookup; the label is what a human reads. A record found
    by ``dia-500-mbps`` still displays as ``DIA 500 Mbps``, and folding the
    display form would lose the capitalisation somebody chose.
    """
    if not label or not label.strip():
        raise SubjectLabelRequiredError
    collapsed = " ".join(label.split())
    return collapsed[:MAX_SUBJECT_LABEL_CHARS]


# --------------------------------------------------------------------------
# Attribute schemas
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AttributeField:
    name: str
    required: bool
    kind: str  # "decimal" | "string" | "integer"
    #: For ``string`` fields with a closed vocabulary.
    allowed: frozenset[str] | None = None
    max_length: int | None = None


#: Per-type attribute contracts. Unknown keys are **rejected rather than
#: stored**: a price carrying a stray ``discount`` nobody validated is a
#: number that will eventually be read as authoritative.
ATTRIBUTE_SCHEMAS: dict[KnowledgeRecordType, tuple[AttributeField, ...]] = {
    KnowledgeRecordType.PRICE: (
        # Currency is a *field*, never part of a formatted string. "180 JOD"
        # cannot be compared, converted or totalled — the invoicing domain
        # already learned this one.
        AttributeField("amount", required=True, kind="decimal"),
        AttributeField("currency", required=True, kind="string", max_length=3),
        AttributeField("unit", required=False, kind="string", max_length=40),
        AttributeField("billing_period", required=False, kind="string", max_length=40),
        AttributeField("tax_treatment", required=False, kind="string", max_length=40),
    ),
    KnowledgeRecordType.PRODUCT: (
        AttributeField("summary", required=False, kind="string", max_length=2000),
        AttributeField("sku", required=False, kind="string", max_length=80),
        AttributeField("category", required=False, kind="string", max_length=80),
    ),
    KnowledgeRecordType.SERVICE: (
        AttributeField("summary", required=False, kind="string", max_length=2000),
        AttributeField("category", required=False, kind="string", max_length=80),
    ),
    KnowledgeRecordType.SLA_TERM: (
        AttributeField("metric", required=True, kind="string", max_length=80),
        AttributeField("target", required=True, kind="string", max_length=80),
        AttributeField("measurement_window", required=False, kind="string", max_length=80),
    ),
    KnowledgeRecordType.POLICY_PARAM: (
        AttributeField("parameter", required=True, kind="string", max_length=80),
        AttributeField("value", required=True, kind="string", max_length=500),
    ),
}

#: ISO-4217 is three uppercase letters. Validated by shape rather than
#: against a list, because the list changes and a wrong-shaped code is the
#: error worth catching.
_CURRENCY = re.compile(r"^[A-Z]{3}$")


def validate_attributes(
    record_type: KnowledgeRecordType, attributes: dict[str, Any]
) -> dict[str, Any]:
    """Checks ``attributes`` against its type's schema and returns it normalised.

    Returns a new dict rather than mutating: the caller's payload is request
    data, and a validator that edits its input makes "what did the user
    send" unanswerable two frames later.
    """
    schema = ATTRIBUTE_SCHEMAS[record_type]
    known = {field.name: field for field in schema}

    unknown = sorted(set(attributes) - set(known))
    if unknown:
        raise AttributeSchemaError(
            f"{record_type} does not have "
            f"{'attributes' if len(unknown) > 1 else 'an attribute'} "
            f"{', '.join(repr(name) for name in unknown)}."
        )

    missing = sorted(
        field.name for field in schema if field.required and attributes.get(field.name) is None
    )
    if missing:
        raise AttributeSchemaError(
            f"{record_type} needs {', '.join(repr(name) for name in missing)}."
        )

    cleaned: dict[str, Any] = {}
    for name, raw in attributes.items():
        if raw is None:
            continue
        cleaned[name] = _clean_attribute(record_type, known[name], raw)
    return cleaned


def _clean_attribute(record_type: KnowledgeRecordType, field: AttributeField, raw: Any) -> Any:
    if field.kind == "decimal":
        return _clean_decimal(field, raw)
    if field.kind == "integer":
        try:
            return int(raw)
        except (TypeError, ValueError) as exc:
            raise AttributeSchemaError(f"{field.name!r} must be a whole number.") from exc

    value = str(raw).strip()
    if not value:
        raise AttributeSchemaError(f"{field.name!r} cannot be blank.")

    # The currency check runs *before* the generic length check. Both would
    # reject "Jordanian", but only one of them tells the caller what a
    # currency is supposed to look like — and "longer than 3 characters" is
    # a worse error for the most likely mistake anybody makes here.
    if record_type is KnowledgeRecordType.PRICE and field.name == "currency":
        value = value.upper()
        if not _CURRENCY.match(value):
            raise AttributeSchemaError(
                f"{value!r} is not an ISO-4217 currency code (three letters)."
            )
        return value

    if field.max_length is not None and len(value) > field.max_length:
        raise AttributeSchemaError(f"{field.name!r} is longer than {field.max_length} characters.")
    if field.allowed is not None and value not in field.allowed:
        raise AttributeSchemaError(
            f"{field.name!r} must be one of {', '.join(sorted(field.allowed))}."
        )
    return value


def _clean_decimal(field: AttributeField, raw: Any) -> str:
    # Stored as a string in JSON so no float ever touches a price. A float
    # round-trip turns 0.1 into 0.1000000000000000055 and a quoted amount
    # into an argument.
    try:
        amount = Decimal(str(raw))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise AttributeSchemaError(f"{field.name!r} must be a number.") from exc
    if amount.is_nan() or amount.is_infinite():
        raise AttributeSchemaError(f"{field.name!r} must be a finite number.")
    if amount < 0:
        raise AttributeSchemaError(f"{field.name!r} cannot be negative.")
    return format(amount, "f")


# --------------------------------------------------------------------------
# Effective period
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class EffectivePeriod:
    """When a record is true. ``until`` of ``None`` means open-ended.

    Half-open: ``from <= t < until``. Half-open is what makes supersession
    exact — the old price stops being true at precisely the instant the new
    one starts, with no shared moment where both are active and no gap where
    neither is.
    """

    effective_from: datetime
    effective_until: datetime | None = None

    def __post_init__(self) -> None:
        if self.effective_until is None:
            return
        if self.effective_until <= self.effective_from:
            raise EffectivePeriodError(
                "A record's effective_until must be after its effective_from."
            )

    def covers(self, moment: datetime) -> bool:
        if moment < self.effective_from:
            return False
        return self.effective_until is None or moment < self.effective_until

    def overlaps(self, other: EffectivePeriod) -> bool:
        """True when two periods share any instant.

        Open-ended periods are handled by the ``is None`` branches rather
        than a sentinel far-future date: a sentinel is a date somebody
        eventually compares against and gets wrong.
        """
        self_ends_first = (
            self.effective_until is not None and other.effective_from >= self.effective_until
        )
        other_ends_first = (
            other.effective_until is not None and self.effective_from >= other.effective_until
        )
        return not (self_ends_first or other_ends_first)


def validate_effective_period(
    effective_from: datetime, effective_until: datetime | None
) -> EffectivePeriod:
    """Constructor that names the rule it enforces."""
    if effective_from.tzinfo is None:
        raise EffectivePeriodError("effective_from must be timezone-aware.")
    if effective_until is not None and effective_until.tzinfo is None:
        raise EffectivePeriodError("effective_until must be timezone-aware.")
    return EffectivePeriod(effective_from=effective_from, effective_until=effective_until)


# --------------------------------------------------------------------------
# Lifecycle
# --------------------------------------------------------------------------

#: What each state may become. Absent transitions are refused rather than
#: ignored, so a caller that assumed the wrong shape finds out.
_ALLOWED_TRANSITIONS: dict[KnowledgeLifecycleState, frozenset[KnowledgeLifecycleState]] = {
    KnowledgeLifecycleState.DRAFT: frozenset(
        {KnowledgeLifecycleState.ACTIVE, KnowledgeLifecycleState.ARCHIVED}
    ),
    KnowledgeLifecycleState.ACTIVE: frozenset(
        {KnowledgeLifecycleState.SUPERSEDED, KnowledgeLifecycleState.ARCHIVED}
    ),
    # Terminal. A superseded record is history; reviving it would mean two
    # versions claiming to be current, which is the state this whole module
    # exists to make impossible.
    KnowledgeLifecycleState.SUPERSEDED: frozenset(),
    KnowledgeLifecycleState.ARCHIVED: frozenset(),
}


def validate_transition(current: KnowledgeLifecycleState, target: KnowledgeLifecycleState) -> None:
    if target not in _ALLOWED_TRANSITIONS[current]:
        raise InvalidLifecycleTransitionError(current.value, target.value)


def validate_publishable(
    *, source_document_version_id: object | None, source_reference: str | None
) -> None:
    """Publishing needs a traceable origin. Drafting does not.

    The asymmetry is the point: a draft is somebody working, and demanding
    provenance before they have finished would push people toward inventing
    one. Becoming authoritative is where the requirement bites.
    """
    if source_document_version_id is None and not (source_reference or "").strip():
        raise ProvenanceRequiredError


__all__ = [
    "ATTRIBUTE_SCHEMAS",
    "MAX_SUBJECT_KEY_CHARS",
    "MAX_SUBJECT_LABEL_CHARS",
    "RESOLVABLE_STATES",
    "SENSITIVE_RECORD_TYPES",
    "AttributeField",
    "AttributeSchemaError",
    "EffectivePeriod",
    "EffectivePeriodError",
    "InvalidLifecycleTransitionError",
    "KnowledgeAccessLevel",
    "KnowledgeLifecycleState",
    "KnowledgeRecordError",
    "KnowledgeRecordType",
    "OverlappingRecordError",
    "ProvenanceRequiredError",
    "SubjectKeyNotDerivableError",
    "SubjectLabelRequiredError",
    "canonical_subject_key",
    "normalise_subject_label",
    "validate_attributes",
    "validate_effective_period",
    "validate_publishable",
    "validate_transition",
]
