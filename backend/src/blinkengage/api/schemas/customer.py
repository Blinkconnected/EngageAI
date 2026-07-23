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
