from uuid import UUID

from pydantic import BaseModel, EmailStr, Field, model_validator


class CsatSurveyLinkResponse(BaseModel):
    url: str


class CsatSubmitRequest(BaseModel):
    rating: int = Field(..., ge=1, le=5)
    comment: str | None = Field(default=None, max_length=2000)


class CsatSubmitResponse(BaseModel):
    conversation_id: UUID
    rating: int
    comment: str | None


class CsatContextResponse(BaseModel):
    conversation_id: UUID
    already_responded: bool
    needs_contact_info: bool


class CsatContactInfoRequest(BaseModel):
    email: EmailStr | None = None
    phone: str | None = Field(default=None, min_length=1, max_length=32)

    @model_validator(mode="after")
    def _require_email_or_phone(self) -> "CsatContactInfoRequest":
        if not self.email and not self.phone:
            raise ValueError("Provide at least an email address or a phone number")
        return self


class CsatContactInfoResponse(BaseModel):
    """Deliberately does NOT echo the stored email/phone back — this
    route needs only the survey token (see csat.py's module docstring on
    the trust model shared with web_chat.py's public endpoints), so
    returning the full Customer row would let anyone holding a forwarded
    survey link (an email chain, a shared inbox, a mail-gateway log)
    retrieve contact details the customer never entered in *this*
    request. The frontend (FeedbackPage.tsx) only ever needs to know the
    submission succeeded to advance to the next step."""

    conversation_id: UUID
