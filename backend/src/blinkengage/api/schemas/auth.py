"""Pydantic request/response schemas for the auth API."""

import re
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field, field_validator


def _validate_password_strength(password: str) -> str:
    if len(password) < 10:
        raise ValueError("Password must be at least 10 characters long")
    if not re.search(r"[A-Za-z]", password):
        raise ValueError("Password must contain at least one letter")
    if not re.search(r"\d", password):
        raise ValueError("Password must contain at least one digit")
    return password


class RegisterRequest(BaseModel):
    company_name: str = Field(..., min_length=2, max_length=255)
    owner_full_name: str = Field(..., min_length=1, max_length=255)
    owner_email: EmailStr
    owner_password: str = Field(..., min_length=10, max_length=128)

    @field_validator("owner_password")
    @classmethod
    def _check_password_strength(cls, value: str) -> str:
        return _validate_password_strength(value)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=1, max_length=128)


class RefreshRequest(BaseModel):
    refresh_token: str


class LogoutRequest(BaseModel):
    refresh_token: str


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
    roles: list[str]
    permissions: list[str]


class RegisterResponse(BaseModel):
    user: UserProfileResponse
    tokens: TokenResponse
