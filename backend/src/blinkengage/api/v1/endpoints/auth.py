"""Authentication, registration, and session (token) management endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, status

from blinkengage.api.deps import get_auth_service, get_current_user
from blinkengage.api.schemas.auth import (
    LoginRequest,
    LogoutRequest,
    RefreshRequest,
    RegisterRequest,
    RegisterResponse,
    TokenResponse,
    UserProfileResponse,
)
from blinkengage.application.services.auth_service import AuthService, effective_permissions
from blinkengage.core.config import get_settings
from blinkengage.core.rate_limit import rate_limit_dependency
from blinkengage.infrastructure.database.models.user import User

router = APIRouter(prefix="/auth", tags=["auth"])

_settings = get_settings()
_auth_rate_limit = rate_limit_dependency(
    scope="auth", limit=_settings.rate_limit_per_minute, window_seconds=60
)


def _user_to_profile(user: User) -> UserProfileResponse:
    roles = sorted({user_role.role.name for user_role in user.user_roles})
    permissions = sorted(effective_permissions(user))
    return UserProfileResponse(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        is_company_owner=user.is_company_owner,
        company={"id": user.company.id, "name": user.company.name, "slug": user.company.slug},
        roles=roles,
        permissions=permissions,
    )


@router.post(
    "/register",
    response_model=RegisterResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(_auth_rate_limit)],
)
async def register(
    payload: RegisterRequest,
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
) -> RegisterResponse:
    """Sign up: creates a new company, its Owner user, and the default
    Owner/Admin/Agent roles, then logs the new Owner in immediately."""
    account = await auth_service.register_company(
        company_name=payload.company_name,
        owner_email=payload.owner_email,
        owner_password=payload.owner_password,
        owner_full_name=payload.owner_full_name,
    )
    tokens = await auth_service.issue_tokens(account.user)
    return RegisterResponse(
        user=_user_to_profile(account.user),
        tokens=TokenResponse(access_token=tokens.access_token, refresh_token=tokens.refresh_token),
    )


@router.post(
    "/login",
    response_model=TokenResponse,
    dependencies=[Depends(_auth_rate_limit)],
)
async def login(
    payload: LoginRequest,
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
) -> TokenResponse:
    user = await auth_service.authenticate(email=payload.email, password=payload.password)
    tokens = await auth_service.issue_tokens(user)
    return TokenResponse(access_token=tokens.access_token, refresh_token=tokens.refresh_token)


@router.post("/refresh", response_model=TokenResponse)
async def refresh(
    payload: RefreshRequest,
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
) -> TokenResponse:
    tokens = await auth_service.refresh(refresh_token=payload.refresh_token)
    return TokenResponse(access_token=tokens.access_token, refresh_token=tokens.refresh_token)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    payload: LogoutRequest,
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
) -> None:
    await auth_service.logout(refresh_token=payload.refresh_token)


@router.get("/me", response_model=UserProfileResponse)
async def me(current_user: Annotated[User, Depends(get_current_user)]) -> UserProfileResponse:
    return _user_to_profile(current_user)
