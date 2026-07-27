from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from blinkengage.domain.rbac import is_known_permission


def _validate_permission_codes(codes: list[str]) -> list[str]:
    unknown = [code for code in codes if not is_known_permission(code)]
    if unknown:
        raise ValueError(f"Unknown permission code(s): {', '.join(sorted(set(unknown)))}")
    return codes


class RoleCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    description: str | None = None
    permission_codes: list[str] = Field(default_factory=list)

    @field_validator("permission_codes")
    @classmethod
    def _check_permission_codes(cls, value: list[str]) -> list[str]:
        return _validate_permission_codes(value)


class RoleUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = None
    permission_codes: list[str] | None = None

    @field_validator("permission_codes")
    @classmethod
    def _check_permission_codes(cls, value: list[str] | None) -> list[str] | None:
        return value if value is None else _validate_permission_codes(value)


class RoleResponse(BaseModel):
    id: UUID
    name: str
    description: str | None
    is_system: bool
    permission_codes: list[str]
    member_count: int
    created_at: datetime
    updated_at: datetime


class PermissionResponse(BaseModel):
    code: str
    description: str


class RoleMemberResponse(BaseModel):
    user_id: UUID
    full_name: str
    email: str


class AgentRoleResponse(BaseModel):
    role_id: UUID
    role_name: str


class AgentRoleUpdateRequest(BaseModel):
    role_id: UUID
