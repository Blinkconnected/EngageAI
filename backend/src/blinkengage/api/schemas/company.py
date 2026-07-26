from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from blinkengage.api.schemas.company_settings import CompanySettingsUpdate
from blinkengage.infrastructure.database.models.company import CompanyStatus


class CompanyUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=255)
    # Only the top-level section(s) actually included get merged into the
    # stored settings blob — see CompanyService.update and
    # docs/architecture/company-onboarding.md.
    settings: CompanySettingsUpdate | None = None


class CompanyResponse(BaseModel):
    id: UUID
    name: str
    slug: str
    status: CompanyStatus
    settings: dict[str, Any]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
