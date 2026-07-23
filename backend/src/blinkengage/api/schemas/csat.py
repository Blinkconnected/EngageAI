from uuid import UUID

from pydantic import BaseModel, Field


class CsatSurveyLinkResponse(BaseModel):
    url: str


class CsatSubmitRequest(BaseModel):
    rating: int = Field(..., ge=1, le=5)
    comment: str | None = Field(default=None, max_length=2000)


class CsatSubmitResponse(BaseModel):
    conversation_id: UUID
    rating: int
    comment: str | None
