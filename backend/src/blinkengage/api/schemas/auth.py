"""Pydantic request/response schemas for the auth API."""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field, field_validator

from blinkengage.api.schemas.validators import validate_password_strength


class RegisterRequest(BaseModel):
    company_name: str = Field(..., min_length=2, max_length=255)
    owner_full_name: str = Field(..., min_length=1, max_length=255)
    owner_email: EmailStr
    owner_password: str = Field(..., min_length=10, max_length=128)
    #: ISO 3166-1 alpha-2. Decides the billing currency, and is fixed
    #: afterwards. Optional so existing clients keep working; omitting it
    #: means the default currency and no country recorded.
    country_code: str | None = Field(default=None, min_length=2, max_length=2)

    @field_validator("owner_password")
    @classmethod
    def _check_password_strength(cls, value: str) -> str:
        return validate_password_strength(value)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=1, max_length=128)


class RefreshRequest(BaseModel):
    refresh_token: str


class LogoutRequest(BaseModel):
    refresh_token: str


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(..., min_length=1, max_length=128)
    new_password: str = Field(..., min_length=10, max_length=128)

    @field_validator("new_password")
    @classmethod
    def _check_password_strength(cls, value: str) -> str:
        return validate_password_strength(value)


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class CompanySummary(BaseModel):
    id: UUID
    name: str
    slug: str
    #: ISO 4217. The frontend formats every amount with this — a JOD
    #: figure shown to three places and a USD one to two.
    billing_currency: str = "USD"
    country_code: str | None = None
    #: Whether the signup owner has confirmed their email address. The
    #: frontend shows a banner while this is false and hides the
    #: controls that would 403 — nobody should be offered a button that
    #: cannot work. Carried here because it is already fetched on every
    #: app load.
    verified: bool = True


class UserProfileResponse(BaseModel):
    id: UUID
    email: str
    full_name: str
    is_company_owner: bool
    company: CompanySummary
    #: Product features this company is entitled to (see
    #: ``domain/features.py``). The frontend hides what isn't here, so
    #: nobody is shown a page that will 402 when they open it. Carried on
    #: the profile because it is already fetched on every app load —
    #: a separate endpoint would be a second round trip for something
    #: needed before the first screen renders.
    features: list[str]
    roles: list[str]
    permissions: list[str]


class RegisterResponse(BaseModel):
    user: UserProfileResponse
    tokens: TokenResponse


class VerifyEmailResponse(BaseModel):
    """The outcome of following a verification link.

    A status string rather than a bare boolean: "already verified",
    "expired" and "invalid" each need a different sentence on screen,
    and collapsing them to `false` makes a customer who did nothing
    wrong think they did.
    """

    status: Literal["verified", "already_verified", "expired", "invalid"]


class ResendVerificationResponse(BaseModel):
    #: False when the address is already verified, or when another link
    #: was sent moments ago. Not an error either way.
    sent: bool


class CountryResponse(BaseModel):
    """A country the signup form can offer.

    Carries the currency so the form can tell somebody *before* they sign
    up which currency they will be billed in — it cannot be changed
    afterwards, so it should not be a surprise.
    """

    code: str
    name: str
    currency: str
    currency_symbol: str
