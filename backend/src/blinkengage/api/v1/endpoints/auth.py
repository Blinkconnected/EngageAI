"""Authentication, registration, and session (token) management endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from blinkengage.api.deps import (
    get_auth_service,
    get_current_user,
    get_feature_service,
    get_verification_service,
)
from blinkengage.api.schemas.auth import (
    ChangePasswordRequest,
    CountryResponse,
    LoginRequest,
    LogoutRequest,
    RefreshRequest,
    RegisterRequest,
    RegisterResponse,
    ResendVerificationResponse,
    TokenResponse,
    UserProfileResponse,
    VerifyEmailResponse,
)
from blinkengage.application.services.auth_service import AuthService, effective_permissions
from blinkengage.application.services.feature_service import FeatureService
from blinkengage.application.services.verification_service import VerificationService
from blinkengage.core.config import get_settings
from blinkengage.core.rate_limit import rate_limit_dependency
from blinkengage.domain.countries import sorted_countries
from blinkengage.domain.features import enabled_feature_keys
from blinkengage.infrastructure.database.models.user import User

router = APIRouter(prefix="/auth", tags=["auth"])

_settings = get_settings()
_auth_rate_limit = rate_limit_dependency(
    scope="auth", limit=_settings.rate_limit_per_minute, window_seconds=60
)


def _company_ref(user: User) -> dict[str, object]:
    if user.company is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "This is a platform administrator account, which has no company context. "
                "Use the platform endpoints under /platform."
            ),
        )
    return {
        "id": user.company.id,
        "name": user.company.name,
        "slug": user.company.slug,
        "billing_currency": user.company.billing_currency,
        "country_code": user.company.country_code,
        "verified": user.company.verified_at is not None,
    }


def _user_to_profile(user: User, features: list[str]) -> UserProfileResponse:
    roles = sorted({user_role.role.name for user_role in user.user_roles})
    permissions = sorted(effective_permissions(user))
    return UserProfileResponse(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        is_company_owner=user.is_company_owner,
        # Unreachable for a platform administrator: `get_current_auth`
        # rejects a company-less token before any route body runs, so
        # every user arriving here has a company. Asserted rather than
        # silently defaulted so a future route that forgets that gate
        # fails loudly instead of emitting a fake company.
        company=_company_ref(user),
        features=features,
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
    verification: Annotated[VerificationService, Depends(get_verification_service)],
) -> RegisterResponse:
    """Sign up: creates a new company, its Owner user, and the default
    Owner/Admin/Agent roles, then logs the new Owner in immediately."""
    account = await auth_service.register_company(
        company_name=payload.company_name,
        owner_email=payload.owner_email,
        owner_password=payload.owner_password,
        owner_full_name=payload.owner_full_name,
        country_code=payload.country_code,
    )
    # Sent here rather than inside `register_company` so a mail failure
    # cannot roll the registration back: a customer whose account was
    # created but whose email bounced can resend, whereas a rolled-back
    # signup leaves them with nothing and an address that now looks
    # taken.
    await verification.send_verification(account.user, company=account.company)

    tokens = await auth_service.issue_tokens(account.user)
    return RegisterResponse(
        # A company that was created a moment ago has no subscription and
        # no overrides, so its entitlements are exactly the catalog
        # defaults — computed rather than re-queried.
        user=_user_to_profile(
            account.user, enabled_feature_keys(plan_features=None, overrides=None)
        ),
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


@router.post(
    "/refresh",
    response_model=TokenResponse,
    dependencies=[Depends(_auth_rate_limit)],
)
async def refresh(
    payload: RefreshRequest,
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
) -> TokenResponse:
    tokens = await auth_service.refresh(refresh_token=payload.refresh_token)
    return TokenResponse(access_token=tokens.access_token, refresh_token=tokens.refresh_token)


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(_auth_rate_limit)],
)
async def logout(
    payload: LogoutRequest,
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
) -> None:
    await auth_service.logout(refresh_token=payload.refresh_token)


@router.get("/me", response_model=UserProfileResponse)
async def me(
    current_user: Annotated[User, Depends(get_current_user)],
    features: Annotated[FeatureService, Depends(get_feature_service)],
) -> UserProfileResponse:
    # `_company_ref` inside `_user_to_profile` turns a company-less
    # (platform) user into a 403, but it runs after this line, so the
    # same case is handled here first. `get_current_auth` already rejects
    # those tokens, which makes this unreachable rather than unlikely.
    company_id = current_user.company_id
    if company_id is None:
        return _user_to_profile(current_user, [])
    enabled = await features.enabled_features(company_id)
    return _user_to_profile(current_user, sorted(key for key, on in enabled.items() if on))


@router.post(
    "/me/password",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(_auth_rate_limit)],
)
async def change_my_password(
    payload: ChangePasswordRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
) -> None:
    """Self-service password change from the agent's own profile — requires
    the current password. Every session (including this one) is logged
    out; the client re-authenticates with the new password."""
    await auth_service.change_password(
        user=current_user,
        current_password=payload.current_password,
        new_password=payload.new_password,
    )


@router.get("/verify-email", response_model=VerifyEmailResponse)
async def verify_email(
    token: str,
    verification: Annotated[VerificationService, Depends(get_verification_service)],
) -> VerifyEmailResponse:
    """Consumes a verification link.

    Unauthenticated: the link arrives in an inbox, and requiring a
    signed-in session to use it would break the common case of opening
    it on a phone.

    Answers 200 for every outcome, including an unknown token. The
    result says what happened, and a 404 here would let anybody probe
    which tokens exist.
    """
    result = await verification.verify(token)
    if result.already_verified:
        return VerifyEmailResponse(status="already_verified")
    if result.expired:
        return VerifyEmailResponse(status="expired")
    if result.unknown:
        return VerifyEmailResponse(status="invalid")
    return VerifyEmailResponse(status="verified")


@router.post(
    "/resend-verification",
    response_model=ResendVerificationResponse,
    dependencies=[Depends(_auth_rate_limit)],
)
async def resend_verification(
    user: Annotated[User, Depends(get_current_user)],
    verification: Annotated[VerificationService, Depends(get_verification_service)],
) -> ResendVerificationResponse:
    """Sends another verification link to the signed-in user.

    Requires a session — an unauthenticated resend endpoint taking an
    email address is a way to mail anybody. Unverified users can still
    sign in, so this is always reachable by the person who needs it.
    """
    sent = await verification.resend(user)
    return ResendVerificationResponse(sent=sent)


@router.get("/countries", response_model=list[CountryResponse])
async def countries() -> list[CountryResponse]:
    """Countries this installation can bill in, for the signup picker.

    Unauthenticated: it is needed to render the signup form. Deliberately
    a curated list rather than all of ISO 3166 — signup must not offer a
    country the billing engine has no prices for, because that produces a
    customer nobody discovers is unbillable until the month closes.
    """
    return [
        CountryResponse(
            code=country.code,
            name=country.name,
            currency=country.currency.code,
            currency_symbol=country.currency.symbol,
        )
        for country in sorted_countries()
    ]
