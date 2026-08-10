"""Shared offset/limit pagination for list endpoints."""

from typing import Generic, TypeVar

from pydantic import BaseModel, Field

ItemT = TypeVar("ItemT")


class PageParams(BaseModel):
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100)

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size


class Page(BaseModel, Generic[ItemT]):
    items: list[ItemT]
    total: int
    page: int
    page_size: int
    #: Present only on the lists that support keyset paging, and only when
    #: there is a further page — ``None`` both for offset-paged responses
    #: and for the last page of a cursor-paged one, so "keep going while
    #: this is set" is the whole client-side rule.
    #:
    #: Added to the shared shape rather than given a response model of its
    #: own: an extra nullable field is invisible to every existing caller,
    #: while a second shape would have meant a second route for each list
    #: and two contracts to keep in step. See ``api.cursors``.
    next_cursor: str | None = None
