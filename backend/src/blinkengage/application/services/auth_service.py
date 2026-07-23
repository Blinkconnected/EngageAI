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

from blinkengage.core.config import Settings
from blinkengage.core.security import (
    InvalidTokenError,
    TokenType,
    create_token,
    decode_token,
    hash_password,
    verify_password,
)
from blinkengage.domain.events import DomainEvent, DomainEventPublisher
from blinkengage.domain.exceptions import AuthenticationError, EntityAlreadyExistsError
from blinkengage.domain.rbac import DEFAULT_ROLE_PERMISSIONS, SystemRole
from blinkengage.infrastructure.cache.refresh_tokens import RefreshTokenStore
from blinkengage.infrastructure.database.models.company import Company, CompanyStatus
from blinkengage.infrastructure.database.models.rbac import Role, RolePermission, UserRole
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
    ) -> RegisteredAccount:
        normalized_email = owner_email.strip().lower()
        if await self._users.get_by_email(normalized_email) is not None:
            raise EntityAlreadyExistsError("User", "email", normalized_email)

        slug = await self._unique_slug(slugify(company_name))
        company = await self._companies.add(
            Company(name=company_name.strip(), slug=slug, status=CompanyStatus.TRIAL)
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

    async def issue_tokens(self, user: User) -> IssuedTokens:
        permissions = sorted(effective_permissions(user))
        access_token, _ = create_token(
            subject=user.id,
            settings=self._settings,
            token_type=TokenType.ACCESS,
            extra_claims={"company_id": str(user.company_id), "permissions": permissions},
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

        # Rotate: the presented refresh token is single-use.
        await self._refresh_tokens.revoke(user_id=user_id, jti=jti)
        return await self.issue_tokens(user)

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
        owner_role: Role | None = None
        for system_role, permission_codes in DEFAULT_ROLE_PERMISSIONS.items():
            role = await self._roles.add(
                Role(company_id=company_id, name=system_role.value, is_system=True)
            )
            for code in permission_codes:
                self._session.add(RolePermission(role_id=role.id, permission_code=code))
            if system_role is SystemRole.OWNER:
                owner_role = role
        await self._session.flush()
        assert owner_role is not None  # OWNER is always present in DEFAULT_ROLE_PERMISSIONS
        return owner_role
