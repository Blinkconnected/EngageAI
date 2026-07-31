"""A company's user accounts, administered by platform staff —
`/api/v1/platform/companies/{company_id}/*`.

Its own module rather than growing `platform.py`, matching the split this
codebase already uses for the pricing, billing and settings halves of the
platform tier.

Gated exactly like the rest of that tier: `get_platform_auth` per route
(never `require_permission` — platform authority lives outside the tenant
RBAC catalog, so no tenant role can be edited into it) and
`deny_read_only_writes` **at router construction**, keyed on the HTTP
method. Declared once here rather than per route so that a route added to
this file later inherits the gate instead of shipping unguarded because
whoever added it did not think about the read-only tier. A read-only
operator can therefore see a customer's users — which is most of what
support needs — and change none of them.

Everything on this surface is scoped to the `company_id` in the path, and
the service re-asserts that scope for every single row it touches. See
`application/services/platform_user_service.py` for why a user id
belonging to another tenant answers 404 rather than 403.

**There is no password-reset route here yet, deliberately.** The contract
this feature was designed against includes one, and the safe shape for it
is settled — a link mailed to the address already on the account, with
the operator never seeing a token and never choosing a password. What
does not exist yet is the flow it would have to reuse: this application
has email verification (`VerificationService`) but no password-reset
token issuer, no `password_reset_tokens` table and no unauthenticated
endpoint to consume such a link (`docs/architecture/auth-rbac.md` still
lists password reset as deferred). The only existing "reset" is
`AgentService.reset_password`, where the caller *chooses* the new
password — precisely the account-takeover primitive an operator must
never hold. Writing a second, console-only token issuer here would be a
parallel credential path with none of the review the first one got, so
the route waits for the real self-service flow to ship and then reuses
it.
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends

from blinkengage.api.deps import (
    deny_read_only_writes,
    get_platform_auth,
    get_platform_user_service,
)
from blinkengage.api.schemas.platform_users import (
    CompanyOwnerTransferRequest,
    CompanyUserActionRequest,
    CompanyUserListResponse,
    CompanyUserResponse,
    CompanyUserRoleRequest,
    CompanyUserRoleResponse,
    CompanyUserStatusRequest,
    VerificationEmailResponse,
)
from blinkengage.application.services.platform_user_service import (
    CompanyUserView,
    PlatformUserService,
)
from blinkengage.core.auth_context import PlatformContext

router = APIRouter(
    prefix="/platform/companies",
    tags=["platform"],
    dependencies=[Depends(deny_read_only_writes)],
)


def _to_response(view: CompanyUserView) -> CompanyUserResponse:
    user = view.user
    return CompanyUserResponse(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        is_active=user.is_active,
        is_company_owner=user.is_company_owner,
        # Reported as a boolean rather than the timestamp: the console
        # asks whether this account is blocked on verification, and
        # `email_verified_at` is a column name, not an answer.
        email_verified=user.email_verified_at is not None,
        last_login_at=user.last_login_at,
        created_at=user.created_at,
        role=(
            CompanyUserRoleResponse(id=view.role.id, name=view.role.name)
            if view.role is not None
            else None
        ),
    )


@router.get("/{company_id}/users", response_model=CompanyUserListResponse)
async def list_company_users(
    company_id: UUID,
    _platform: Annotated[PlatformContext, Depends(get_platform_auth)],
    service: Annotated[PlatformUserService, Depends(get_platform_user_service)],
) -> CompanyUserListResponse:
    """One company's user accounts — never another's, never a platform
    administrator, never a deleted one."""
    items, total = await service.list_users(company_id=company_id)
    return CompanyUserListResponse(items=[_to_response(item) for item in items], total=total)


@router.patch("/{company_id}/users/{user_id}/status", response_model=CompanyUserResponse)
async def set_company_user_status(
    company_id: UUID,
    user_id: UUID,
    payload: CompanyUserStatusRequest,
    platform: Annotated[PlatformContext, Depends(get_platform_auth)],
    service: Annotated[PlatformUserService, Depends(get_platform_user_service)],
) -> CompanyUserResponse:
    """Locks one account out, or lets it back in.

    The reversible half of account administration, and the reason there
    is no delete here: a disputed or compromised account can be stopped
    now and restored intact later, and deleting somebody else's user is
    not an operator's decision to make.
    """
    return _to_response(
        await service.set_active(
            company_id=company_id,
            user_id=user_id,
            is_active=payload.is_active,
            reason=payload.reason,
            actor_user_id=platform.user_id,
        )
    )


@router.post("/{company_id}/users/{user_id}/verification", response_model=VerificationEmailResponse)
async def resend_company_user_verification(
    company_id: UUID,
    user_id: UUID,
    payload: CompanyUserActionRequest,
    platform: Annotated[PlatformContext, Depends(get_platform_auth)],
    service: Annotated[PlatformUserService, Depends(get_platform_user_service)],
) -> VerificationEmailResponse:
    """Sends the verification email again, to the address already on the
    account.

    The common support call this surface exists for: the first message
    went to spam, and the customer cannot act until it is confirmed. The
    operator chooses neither the recipient nor the token.
    """
    return VerificationEmailResponse(
        sent_to=await service.resend_verification(
            company_id=company_id,
            user_id=user_id,
            reason=payload.reason,
            actor_user_id=platform.user_id,
        )
    )


@router.put("/{company_id}/users/{user_id}/role", response_model=CompanyUserResponse)
async def set_company_user_role(
    company_id: UUID,
    user_id: UUID,
    payload: CompanyUserRoleRequest,
    platform: Annotated[PlatformContext, Depends(get_platform_auth)],
    service: Annotated[PlatformUserService, Depends(get_platform_user_service)],
) -> CompanyUserResponse:
    """Moves a user to one of their own company's roles.

    A PUT, not a PATCH: a user holds exactly one role, so the body
    replaces it rather than merging into a set.
    """
    return _to_response(
        await service.set_role(
            company_id=company_id,
            user_id=user_id,
            role_id=payload.role_id,
            reason=payload.reason,
            actor_user_id=platform.user_id,
        )
    )


@router.post("/{company_id}/owner", response_model=CompanyUserResponse)
async def transfer_company_ownership(
    company_id: UUID,
    payload: CompanyOwnerTransferRequest,
    platform: Annotated[PlatformContext, Depends(get_platform_auth)],
    service: Annotated[PlatformUserService, Depends(get_platform_user_service)],
) -> CompanyUserResponse:
    """Hands ownership of a company to another of its users.

    On the company rather than on a user, because it is one company-level
    fact — who owns this — and not an edit to two accounts that a client
    could half-apply. The recipient is named in the body, so there is no
    way to spell "remove the owner".
    """
    return _to_response(
        await service.transfer_ownership(
            company_id=company_id,
            user_id=payload.user_id,
            reason=payload.reason,
            actor_user_id=platform.user_id,
        )
    )
