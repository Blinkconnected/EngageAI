from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class ErpConfigCreateRequest(BaseModel):
    base_url: str = Field(..., min_length=1, max_length=500)
    credentials: dict[str, Any] = Field(default_factory=dict)
    webhook_secret: str | None = None


class ErpConfigUpdateRequest(BaseModel):
    base_url: str | None = Field(default=None, min_length=1, max_length=500)
    credentials: dict[str, Any] | None = None
    webhook_secret: str | None = None
    is_active: bool | None = None


class ErpConfigResponse(BaseModel):
    """Deliberately excludes ``credentials``/``webhook_secret`` — secrets
    are write-only over this API, never echoed back once stored (same
    contract as ``ChannelConfigResponse``)."""

    id: UUID
    base_url: str
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ErpSyncedRecordResponse(BaseModel):
    id: UUID
    doctype: str
    external_name: str
    data: dict[str, Any]
    external_modified_at: datetime | None
    synced_at: datetime

    model_config = {"from_attributes": True}


class ErpCustomerLinkResponse(BaseModel):
    customer_id: UUID
    erp_customer_name: str
    synced_at: datetime

    model_config = {"from_attributes": True}
