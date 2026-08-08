"""What an FAQ *is*, and why it is not a knowledge article.

Pure: no I/O, no clock, no repository — the same constraint
``domain/chunking.py`` and ``domain/memory.py`` hold, and for the same
reason: the exact string an FAQ is embedded under has to be derivable
without a database, or the hash and the vector drift apart.

**Why this is its own entity rather than a flag on ``KnowledgeArticle``.**
The AI Engine originally treated "Knowledge Search" and "FAQ Search" as
one capability, on the honest grounds that *"this project's Knowledge Base
never named a distinct FAQ entity for a parallel search to be built
against"* (``ai_service.answer_from_knowledge_base``). Naming one changes
that, and four differences justify a table rather than a column:

1. **The retrieval key is different.** An article is found by matching
   prose inside a long body; an FAQ is found by matching *a question*
   against a canonical question. Those are different targets, and the
   second one is why an FAQ answers a customer's phrasing better than any
   article ever will.
2. **An FAQ needs no chunking.** A question and a short answer are one
   embeddable unit. Forcing them through ``knowledge_chunks`` would mean
   a chunk row per FAQ with ``ordinal=0`` and a null heading path
   forever, plus a per-chunk incremental-hash machinery that can never
   have more than one chunk to be incremental about.
3. **FAQs are ordered.** They are rendered as a list a human curates.
   ``display_order`` is meaningless on an article and load-bearing here.
4. **FAQs face the customer.** A knowledge article is internal by
   default and read by agents; an FAQ is written to be shown. That is
   the difference that makes ``is_published`` default to *false* here
   and *true* there — see ``DEFAULT_IS_PUBLISHED``.

The ``embeddings`` table needed no change to accommodate this: its
``owner_type``/``owner_id`` pair is polymorphic precisely so new owners
can arrive without a migration, and ``OWNER_FAQ`` is the second kind to
use it.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from blinkengage.domain.exceptions import DomainError

#: An FAQ is created **unpublished**, unlike a knowledge article.
#:
#: The asymmetry is deliberate and is the clearest expression of why this
#: is a separate entity. An unfinished article is visible to agents, who
#: can tell a draft from a policy. An unfinished FAQ is visible to
#: *customers*, who cannot — so publishing has to be something somebody
#: chose, not something that happened because they saved a row.
DEFAULT_IS_PUBLISHED = False

#: Bounds, chosen so the shape stays a *question and answer* rather than
#: drifting into a second article store. An FAQ that needs more than this
#: is an article, and the platform already has those.
MAX_QUESTION_CHARS = 500
MAX_ANSWER_CHARS = 8000

#: Below this an "answer" is not one. Matches the spirit of the Learning
#: platform's own too-short floor: "ok" is real, and worth nothing.
MIN_ANSWER_CHARS = 2

#: Locales the platform can meaningfully tell apart today.
#:
#: Deliberately the same vocabulary ``domain/learning_features`` detects
#: rather than a new one — a company tagging an FAQ ``ar`` and the
#: extractor reporting ``ar`` should mean the same thing. ``None`` is a
#: first-class answer: an FAQ that applies regardless of language (a
#: price, a phone number) should not be forced to pick one.
SUPPORTED_LOCALES: frozenset[str] = frozenset({"ar", "en"})


class FaqError(DomainError):
    """Base for FAQ contract violations.

    A ``DomainError`` so the API boundary renders it as a 400 naming what
    is wrong, rather than letting it surface as a 500 that says the
    platform broke when in fact the caller did.
    """


class FaqQuestionRequiredError(FaqError):
    def __init__(self) -> None:
        super().__init__("an FAQ must have a question")


class FaqAnswerRequiredError(FaqError):
    def __init__(self) -> None:
        super().__init__("an FAQ must have an answer")


class FaqTooLongError(FaqError):
    def __init__(self, *, field: str, limit: int) -> None:
        super().__init__(
            f"an FAQ's {field} may not exceed {limit} characters — anything longer "
            "belongs in a knowledge article"
        )
        self.field = field
        self.limit = limit


class UnknownLocaleError(FaqError):
    def __init__(self, *, locale: str) -> None:
        super().__init__(
            f"{locale!r} is not a locale this platform distinguishes; "
            f"expected one of {sorted(SUPPORTED_LOCALES)} or none"
        )
        self.locale = locale


@dataclass(frozen=True)
class FaqContent:
    """The two fields that decide what an FAQ means and how it is found."""

    question: str
    answer: str


def normalise_locale(locale: str | None) -> str | None:
    """Folds a caller's locale onto the supported set, or refuses it.

    ``"EN"``, ``"en-GB"`` and ``"en"`` are one locale as far as this
    platform can act on the difference, so they fold together rather than
    creating three buckets a filter would then have to know about. A
    locale outside the set is refused rather than stored: a silently
    accepted ``"fr"`` would produce an FAQ that no language filter ever
    returns, which looks exactly like the FAQ having been lost.
    """
    if locale is None:
        return None
    cleaned = locale.strip().lower()
    if not cleaned:
        return None
    base = cleaned.split("-", 1)[0]
    if base not in SUPPORTED_LOCALES:
        raise UnknownLocaleError(locale=locale)
    return base


def validate_content(content: FaqContent) -> None:
    """The contract every stored FAQ satisfies.

    Called by the service before anything reaches the session, so "every
    FAQ has a question and an answer" is a property of the store rather
    than a habit of its callers — the same posture
    ``memory.validate_fact_shape`` takes.
    """
    question = content.question.strip()
    answer = content.answer.strip()

    if not question:
        raise FaqQuestionRequiredError()
    if len(answer) < MIN_ANSWER_CHARS:
        raise FaqAnswerRequiredError()
    if len(question) > MAX_QUESTION_CHARS:
        raise FaqTooLongError(field="question", limit=MAX_QUESTION_CHARS)
    if len(answer) > MAX_ANSWER_CHARS:
        raise FaqTooLongError(field="answer", limit=MAX_ANSWER_CHARS)


def embeddable_text(content: FaqContent) -> str:
    """What actually gets embedded: the question, then the answer.

    **Both, not the question alone.** Embedding only the question makes an
    FAQ unfindable by a term that appears solely in its answer — a product
    name, a fee, a branch — which is a large share of what customers
    actually type. Embedding only the answer loses the phrasing that makes
    an FAQ match a question in the first place.

    Kept here, beside the validator, for the reason
    ``chunking.embeddable_text`` gives: the string the content hash is
    computed over and the string sent to the provider must be the same
    one, or every FAQ looks changed on every sweep and the incremental
    path quietly becomes a full one.
    """
    return f"{content.question.strip()}\n\n{content.answer.strip()}"


def next_display_order(existing: list[int]) -> int:
    """Where a newly created FAQ goes: the end.

    Appending rather than inserting at the top, because an FAQ list is
    curated — the order is somebody's editorial decision, and a new entry
    silently taking the first slot would rewrite it. Reordering is an
    explicit, separate act.
    """
    return (max(existing) + 1) if existing else 0


def reordered(*, current: list[UUID], ordered_ids: list[UUID]) -> dict[UUID, int]:
    """Maps id -> new ``display_order`` for an explicit reorder.

    Ids absent from ``ordered_ids`` keep their relative order **after**
    the ones named, rather than being dropped or shuffled to the front. A
    caller reordering the three FAQs visible on one screen must not
    silently reorder the forty it never loaded — which is what a
    "replace the whole list" contract would do to anybody using a filter.
    """
    named = [faq_id for faq_id in ordered_ids if faq_id in set(current)]
    remainder = [faq_id for faq_id in current if faq_id not in set(named)]
    return {faq_id: index for index, faq_id in enumerate([*named, *remainder])}


__all__ = [
    "DEFAULT_IS_PUBLISHED",
    "MAX_ANSWER_CHARS",
    "MAX_QUESTION_CHARS",
    "MIN_ANSWER_CHARS",
    "SUPPORTED_LOCALES",
    "FaqAnswerRequiredError",
    "FaqContent",
    "FaqError",
    "FaqQuestionRequiredError",
    "FaqTooLongError",
    "UnknownLocaleError",
    "embeddable_text",
    "next_display_order",
    "normalise_locale",
    "reordered",
    "validate_content",
]
