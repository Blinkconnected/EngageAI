"""Auth/RBAC application service.

Orchestrates registration (company + owner user + seeded roles), login,
token refresh (with rotation), and logout. This is the one place that
knows how repositories, the token store, and JWT issuance fit together —
API route handlers stay thin and framework-focused.
"""

import re
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from blinkengage.application.services.permission_sync_service import PermissionSyncService
from blinkengage.core.config import Settings
from blinkengage.core.security import (
    InvalidTokenError,
    TokenType,
    create_token,
    decode_token,
    hash_password,
    verify_password,
)
from blinkengage.domain.collections import PRODUCT_BLOCKING_STATUSES
from blinkengage.domain.company_settings import min_password_length
from blinkengage.domain.countries import require_country
from blinkengage.domain.events import DomainEvent, DomainEventPublisher
from blinkengage.domain.exceptions import (
    AuthenticationError,
    CompanyNotActiveError,
    EntityAlreadyExistsError,
    WeakPasswordError,
)
from blinkengage.domain.money import DEFAULT_CURRENCY
from blinkengage.domain.rbac import SystemRole
from blinkengage.infrastructure.cache.refresh_tokens import RefreshTokenStore
from blinkengage.infrastructure.database.models.company import Company, CompanyStatus
from blinkengage.infrastructure.database.models.rbac import Role, UserRole
from blinkengage.infrastructure.database.models.user import User
from blinkengage.infrastructure.repositories.company_repository import CompanyRepository
from blinkengage.infrastructure.repositories.role_repository import RoleRepository
from blinkengage.infrastructure.repositories.user_repository import UserRepository

# A bcrypt hash of a random, never-used password. Verified against on a
# failed lookup so login takes the same code path (and roughly the same
# time) whether or not the email exists, to reduce user-enumeration risk.
_DUMMY_PASSWORD_HASH = hash_password(secrets.token_urlsafe(32))

_SLUG_INVALID_CHARS = re.compile(r"[^a-z0-9]+")


def slugify(value: str) -> str:
    slug = _SLUG_INVALID_CHARS.sub("-", value.lower()).strip("-")
    return slug or "company"


@dataclass(frozen=True, slots=True)
class IssuedTokens:
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


@dataclass(frozen=True, slots=True)
class RegisteredAccount:
    company: Company
    user: User


def effective_permissions(user: User) -> frozenset[str]:
    codes: set[str] = set()
    for user_role in user.user_roles:
        for role_permission in user_role.role.role_permissions:
            codes.add(role_permission.permission_code)
    return frozenset(codes)


class AuthService:
    def __init__(
        self,
        *,
        settings: Settings,
        session: AsyncSession,
        companies: CompanyRepository,
        users: UserRepository,
        roles: RoleRepository,
        refresh_tokens: RefreshTokenStore,
        events: DomainEventPublisher,
    ) -> None:
        self._settings = settings
        self._session = session
        self._companies = companies
        self._users = users
        self._roles = roles
        self._refresh_tokens = refresh_tokens
        self._events = events

    async def register_company(
        self,
        *,
        company_name: str,
        owner_email: str,
        owner_password: str,
        owner_full_name: str,
        country_code: str | None = None,
    ) -> RegisteredAccount:
        normalized_email = owner_email.strip().lower()
        if await self._users.get_by_email(normalized_email) is not None:
            raise EntityAlreadyExistsError("User", "email", normalized_email)

        # The country decides the billing currency, and it is fixed from
        # here: re-denominating issued invoices and ledger entries is
        # never safe. An unrecognised country is refused rather than
        # defaulted — signup that accepts a country the billing engine has
        # no prices for produces a customer nobody discovers is
        # unbillable until the month closes.
        country = require_country(country_code) if country_code else None

        slug = await self._unique_slug(slugify(company_name))
        company = await self._companies.add(
            Company(
                name=company_name.strip(),
                slug=slug,
                status=CompanyStatus.TRIAL,
                country_code=country.code if country else None,
                billing_currency=(country.currency.code if country else DEFAULT_CURRENCY.code),
            )
        )

        user = await self._users.add(
            User(
                company_id=company.id,
                email=normalized_email,
                hashed_password=hash_password(owner_password),
                full_name=owner_full_name.strip(),
                is_company_owner=True,
            )
        )

        owner_role = await self._seed_default_roles(company_id=company.id)
        self._session.add(UserRole(user_id=user.id, role_id=owner_role.id))
        await self._session.flush()

        # Reload with relationships populated for the caller (e.g. to issue tokens immediately).
        reloaded = await self._users.get_by_id(user.id)
        assert reloaded is not None
        await self._events.publish(
            DomainEvent(
                event_type="company.registered",
                company_id=company.id,
                aggregate_type="company",
                aggregate_id=company.id,
                actor_user_id=reloaded.id,
                payload={"company_name": company.name, "owner_email": normalized_email},
            )
        )
        return RegisteredAccount(company=company, user=reloaded)

    async def authenticate(self, *, email: str, password: str) -> User:
        user = await self._users.get_by_email(email.strip().lower())
        if user is None:
            verify_password(password, _DUMMY_PASSWORD_HASH)
            raise AuthenticationError("Invalid email or password")

        if not verify_password(password, user.hashed_password) or not user.is_active:
            raise AuthenticationError("Invalid email or password")

        await self._assert_company_usable(user)

        user.last_login_at = datetime.now(UTC)
        await self._events.publish(
            DomainEvent(
                event_type="user.login",
                company_id=user.company_id,
                aggregate_type="user",
                aggregate_id=user.id,
                actor_user_id=user.id,
                payload={},
            )
        )
        return user

    async def _assert_company_usable(self, user: User) -> None:
        """Blocks sign-in for a suspended or deleted company.

        Enforced on both `authenticate` and `refresh` so a suspension
        takes effect at the next token refresh at the latest (the same
        ~15-minute bound `auth_context.py` documents for permission
        changes); `deps.get_current_user` re-checks it per request, which
        closes that window for anything going through the API.

        A platform administrator has no company and is deliberately
        exempt — suspending a tenant must never lock out the operator who
        needs to un-suspend it.
        """
        if user.company_id is None:
            return
        company = await self._companies.get_by_id(user.company_id)
        if company is None or company.deleted_at is not None:
            # A soft-deleted company's users could previously keep
            # signing in indefinitely — nothing read `deleted_at` on any
            # auth path.
            raise CompanyNotActiveError("closed")
        if company.status is CompanyStatus.SUSPENDED:
            raise CompanyNotActiveError("suspended")
        # Billing suspension is checked *after* compliance suspension and
        # never instead of it: a company can be in both, and the
        # compliance one is not lifted by paying.
        #
        # Unlike compliance suspension this one has an exemption —
        # anyone who can see the bill can still sign in. Locking the
        # billing administrator out of a workspace suspended for
        # non-payment leaves nobody able to pay, which turns a late
        # invoice into a permanently lost customer.
        if (
            company.billing_status in PRODUCT_BLOCKING_STATUSES
            and "billing.read" not in effective_permissions(user)
        ):
            raise CompanyNotActiveError("payment_suspended")

    async def issue_tokens(self, user: User) -> IssuedTokens:
        permissions = sorted(effective_permissions(user))
        # A platform administrator's token carries no `company_id` claim
        # at all — that absence is precisely what `get_current_auth` uses
        # to refuse it on tenant endpoints, and what `get_platform_auth`
        # expects. It also carries no tenant permissions: platform
        # authority is re-read from the database per request.
        extra_claims: dict[str, object] = {"permissions": permissions}
        if user.company_id is not None:
            extra_claims["company_id"] = str(user.company_id)
        access_token, _ = create_token(
            subject=user.id,
            settings=self._settings,
            token_type=TokenType.ACCESS,
            extra_claims=extra_claims,
        )
        refresh_token, refresh_jti = create_token(
            subject=user.id, settings=self._settings, token_type=TokenType.REFRESH
        )
        await self._refresh_tokens.store(
            user_id=user.id,
            jti=refresh_jti,
            ttl=timedelta(days=self._settings.refresh_token_expire_days),
        )
        return IssuedTokens(access_token=access_token, refresh_token=refresh_token)

    async def refresh(self, *, refresh_token: str) -> IssuedTokens:
        try:
            payload = decode_token(
                refresh_token, settings=self._settings, expected_type=TokenType.REFRESH
            )
        except InvalidTokenError as exc:
            raise AuthenticationError("Invalid or expired refresh token") from exc

        user_id = uuid.UUID(payload["sub"])
        jti = payload["jti"]

        if not await self._refresh_tokens.is_valid(user_id=user_id, jti=jti):
            raise AuthenticationError("Refresh token has been revoked")

        user = await self._users.get_by_id(user_id)
        if user is None or not user.is_active:
            raise AuthenticationError("Account is no longer active")
        await self._assert_company_usable(user)

        # Rotate: the presented refresh token is single-use.
        await self._refresh_tokens.revoke(user_id=user_id, jti=jti)
        return await self.issue_tokens(user)

    async def change_password(
        self, *, user: User, current_password: str, new_password: str
    ) -> None:
        """Self-service password change from the agent's own profile —
        unlike ``AgentService.reset_password`` (an Owner/Admin action on
        someone else's account), this always requires the current
        password. Revokes every refresh token issued under the old
        password, including the session making this request — the client
        is expected to log in again with the new password, same as after
        any other password change."""
        if not verify_password(current_password, user.hashed_password):
            raise AuthenticationError("Current password is incorrect")

        # A platform administrator belongs to no company, so there is no
        # company-configured minimum to apply — the global default in
        # `min_password_length` still governs via the `None` branch below.
        company = (
            await self._companies.get_by_id(user.company_id)
            if user.company_id is not None
            else None
        )
        if company is not None:
            required_length = min_password_length(company.settings)
            if len(new_password) < required_length:
                raise WeakPasswordError(required_length)

        user.hashed_password = hash_password(new_password)
        await self._refresh_tokens.revoke_all_for_user(user_id=user.id)
        await self._events.publish(
            DomainEvent(
                event_type="user.password_changed",
                company_id=user.company_id,
                aggregate_type="user",
                aggregate_id=user.id,
                actor_user_id=user.id,
                payload={},
            )
        )

    async def logout(self, *, refresh_token: str) -> None:
        try:
            payload = decode_token(
                refresh_token, settings=self._settings, expected_type=TokenType.REFRESH
            )
        except InvalidTokenError:
            return  # Already invalid/expired — nothing to revoke.

        user_id = uuid.UUID(payload["sub"])
        await self._refresh_tokens.revoke(user_id=user_id, jti=payload["jti"])

        user = await self._users.get_by_id(user_id)
        if user is not None:
            await self._events.publish(
                DomainEvent(
                    event_type="user.logout",
                    company_id=user.company_id,
                    aggregate_type="user",
                    aggregate_id=user.id,
                    actor_user_id=user.id,
                    payload={},
                )
            )

    async def _unique_slug(self, base_slug: str) -> str:
        candidate = base_slug
        while await self._companies.get_by_slug(candidate) is not None:
            candidate = f"{base_slug}-{secrets.token_hex(3)}"
        return candidate

    async def _seed_default_roles(self, *, company_id: uuid.UUID) -> Role:
        """Delegates to the same generic sync used to backfill existing
        companies (``PermissionSyncService`` /
        ``infrastructure.database.permission_sync``) rather than a
        second, hand-rolled "create a role per ``DEFAULT_ROLE_PERMISSIONS``
        entry" loop — a brand-new company with zero roles is just the
        sync's "everything is missing" case. One implementation for
        both "seed a new company" and "backfill an existing one" means
        they can never drift apart again."""
        await PermissionSyncService(self._session).sync(company_id=company_id)
        owner_role = await self._roles.get_by_name(
            company_id=company_id, name=SystemRole.OWNER.value
        )
        assert owner_role is not None  # sync_permissions always creates every SystemRole's row
        return owner_role
