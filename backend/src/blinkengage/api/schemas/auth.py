"""Pydantic request/response schemas for the auth API."""

from uuid import UUID

from pydantic import BaseModel, EmailStr, Field, field_validator

from blinkengage.api.schemas.validators import validate_password_strength


class RegisterRequest(BaseModel):
    company_name: str = Field(..., min_length=2, max_length=255)
    owner_full_name: str = Field(..., min_length=1, max_length=255)
    owner_email: EmailStr
    owner_password: str = Field(..., min_length=10, max_length=128)

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
