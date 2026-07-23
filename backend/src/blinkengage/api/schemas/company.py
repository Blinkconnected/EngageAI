from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from blinkengage.infrastructure.database.models.company import CompanyStatus


class CompanyUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=255)
    settings: dict[str, Any] | None = None


class CompanyResponse(BaseModel):
    id: UUID
    name: str
    slug: str
    status: CompanyStatus
    settings: dict[str, Any]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
