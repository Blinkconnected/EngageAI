from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel


class NotificationResponse(BaseModel):
    id: UUID
    notification_type: str
    title: str
    body: str
    payload: dict[str, Any]
    is_read: bool
    read_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}


class UnreadCountResponse(BaseModel):
    unread_count: int


class NotificationPreferenceItem(BaseModel):
    notification_type: str
    label: str
    channel: str
    enabled: bool


class NotificationPreferencesResponse(BaseModel):
    items: list[NotificationPreferenceItem]


class NotificationPreferenceUpdateRequest(BaseModel):
    notification_type: str
    channel: str
    enabled: bool
