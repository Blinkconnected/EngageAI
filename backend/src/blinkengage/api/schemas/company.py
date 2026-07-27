from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

from blinkengage.api.schemas.company_settings import CompanySettingsUpdate
from blinkengage.infrastructure.database.models.company import CompanyStatus

AiConfigProvider = Literal[
    "openai", "claude", "gemini", "azure_openai", "ollama", "mistral", "groq", "deepseek"
]


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


class AiConfigUpdateRequest(BaseModel):
    """``provider: None`` clears the company's override entirely, reverting
    to the platform-level ``settings.ai_provider`` default. ``api_key:
    None`` (the default — simply omitted) leaves any previously-saved key
    untouched, so changing the model or base URL doesn't force re-entering
    it; pass an explicit non-empty string to set/replace it. There is no
    way to *clear* a saved key without clearing the whole provider, by
    design — a stored-but-unusable half-configured provider is a worse
    state than "no override" (see CompanyService.update_ai_config)."""

    provider: AiConfigProvider | None = None
    api_key: str | None = Field(default=None, min_length=1)
    model: str | None = Field(default=None, min_length=1, max_length=200)
    base_url: str | None = Field(default=None, min_length=1, max_length=500)
    # Azure OpenAI only — every other provider ignores these. base_url
    # above doubles as Azure's "resource endpoint" (e.g.
    # https://my-resource.openai.azure.com), so these two are the only
    # genuinely new fields Azure needs.
    deployment_name: str | None = Field(default=None, min_length=1, max_length=200)
    api_version: str | None = Field(default=None, min_length=1, max_length=50)


class AiConfigResponse(BaseModel):
    """Never carries the raw API key — ``api_key_set`` is the only signal
    the frontend gets about it, matching this codebase's existing
    write-only-secret convention (e.g. channel credentials)."""

    provider: AiConfigProvider | None
    model: str | None
    base_url: str | None
    api_key_set: bool
    deployment_name: str | None
    api_version: str | None
