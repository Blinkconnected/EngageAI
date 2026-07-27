from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class CustomerCreateRequest(BaseModel):
    full_name: str = Field(..., min_length=1, max_length=255)
    email: str | None = None
    phone: str | None = None
    notes: str | None = None
    custom_fields: dict[str, Any] = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list)


class CustomerUpdateRequest(BaseModel):
    full_name: str | None = Field(default=None, min_length=1, max_length=255)
    email: str | None = None
    phone: str | None = None
    notes: str | None = None
    custom_fields: dict[str, Any] | None = None
    tags: list[str] | None = None


class CustomerResponse(BaseModel):
    id: UUID
    full_name: str
    email: str | None
    phone: str | None
    notes: str | None
    custom_fields: dict[str, Any]
    tags: list[str]
    created_at: datetime
    updated_at: datetime
    # P3.15 — internal customer ratings (see CustomerInternalRatingResponse
    # for the full history): a summary embedded here so every place that
    # already fetches a Customer (profile page, customer list, the
    # conversation workspace's customer sidebar) gets it for free, without
    # a second request. `None`/`0` when nobody has rated this customer yet.
    rating_average: float | None = None
    rating_count: int = 0


class CustomerInternalRatingCreateRequest(BaseModel):
    stars: int = Field(..., ge=1, le=5)
    note: str | None = Field(default=None, max_length=2000)


class CustomerInternalRatingUpdateRequest(BaseModel):
    stars: int = Field(..., ge=1, le=5)
    note: str | None = Field(default=None, max_length=2000)


class CustomerInternalRatingResponse(BaseModel):
    id: UUID
    customer_id: UUID
    rated_by_user_id: UUID | None
    stars: int
    note: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
