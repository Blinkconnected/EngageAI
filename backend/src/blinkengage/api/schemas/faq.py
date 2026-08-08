from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from blinkengage.domain.faq import MAX_ANSWER_CHARS, MAX_QUESTION_CHARS


class FaqCreateRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=MAX_QUESTION_CHARS)
    answer: str = Field(..., min_length=1, max_length=MAX_ANSWER_CHARS)
    category_id: UUID | None = None
    #: ``ar`` / ``en``. Omit it for an answer that applies whatever the
    #: customer speaks — a price, a phone number, an address.
    locale: str | None = Field(default=None, max_length=8)
    #: Defaults to unpublished at the service layer, deliberately: an FAQ
    #: is customer-facing, so being visible has to be a decision somebody
    #: made rather than a side effect of saving a draft.
    is_published: bool | None = None
    tags: list[str] = Field(default_factory=list)


class FaqUpdateRequest(BaseModel):
    question: str | None = Field(default=None, min_length=1, max_length=MAX_QUESTION_CHARS)
    answer: str | None = Field(default=None, min_length=1, max_length=MAX_ANSWER_CHARS)
    category_id: UUID | None = None
    locale: str | None = Field(default=None, max_length=8)
    is_published: bool | None = None
    tags: list[str] | None = None


class FaqReorderRequest(BaseModel):
    """The ids to move, in their new order.

    Partial by design — ids left out keep their relative order *after*
    the ones named, so reordering a filtered screen cannot silently
    reshuffle the FAQs that screen never loaded.
    """

    ordered_ids: list[UUID] = Field(..., min_length=1)


class FaqResponse(BaseModel):
    id: UUID
    category_id: UUID | None
    question: str
    answer: str
    is_published: bool
    locale: str | None
    display_order: int
    tags: list[str]
    #: Whether this FAQ is currently retrievable by semantic search.
    #: Surfaced rather than kept internal for the reason
    #: ``GET /knowledge/index-status`` exists: every failure mode of a
    #: background indexer is invisible from outside — search simply
    #: returns less — and an author needs to see that the answer they
    #: just wrote is not findable yet.
    index_state: str
    created_at: datetime
    updated_at: datetime


class FaqSearchHit(BaseModel):
    """One hybrid-retrieval result.

    ``sources`` and ``ranks`` are returned rather than kept server-side
    because the first question anybody asks of a search result is "why is
    this here?" — and an administrator comparing FAQ search against the
    substring matching it replaced needs to see which half found what.
    """

    faq: FaqResponse
    score: float
    sources: list[str]
    ranks: dict[str, int]


class FaqSearchResponse(BaseModel):
    hits: list[FaqSearchHit]
    #: Which retrievers ran. Empty when nothing matched.
    sources: list[str]
    #: True when semantic retrieval was unavailable and this is a
    #: lexical-only result. Returned rather than logged: a caller that
    #: cannot tell a degraded search from a complete one will report
    #: "search is broken" for what is in fact "embeddings are switched
    #: off".
    degraded: bool
    reason: str | None = None
