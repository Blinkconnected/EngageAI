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

from sqlalchemy import select
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
from blinkengage.domain.service_context import AiPolicy
from blinkengage.infrastructure.cache.refresh_tokens import RefreshTokenStore
from blinkengage.infrastructure.database.models.company import Company, CompanyStatus
from blinkengage.infrastructure.database.models.queue import Queue, RoutingRule
from blinkengage.infrastructure.database.models.rbac import Role, UserRole
from blinkengage.infrastructure.database.models.service_directory import (
    Service,
    ServiceVersion,
)
from blinkengage.infrastructure.database.models.user import User
from blinkengage.infrastructure.repositories.company_repository import CompanyRepository
from blinkengage.infrastructure.repositories.role_repository import RoleRepository
from blinkengage.infrastructure.repositories.user_repository import UserRepository

#: What a brand-new company's queue is called. Named for what it is rather
#: than for the company: an administrator renames it in one click, and "Acme
#: Support" pre-filled by the platform reads as a decision somebody made.
DEFAULT_QUEUE_NAME = "General"
DEFAULT_QUEUE_DESCRIPTION = "Every conversation arrives here until you add queues of your own."
#: Lower than any rule an administrator is likely to write, so their routing
#: always wins and this only catches what nothing else claimed.
DEFAULT_RULE_PRIORITY = 1000

#: The company's first Service. Named for what it is rather than for the
#: queue it feeds, because a company that later splits into several will
#: rename this one rather than delete it.
DEFAULT_SERVICE_CODE = "general"
DEFAULT_SERVICE_NAME = "General"
DEFAULT_SERVICE_DESCRIPTION = (
    "What this company promises: response targets and AI policy. Edit it, "
    "rename it, or add services of your own alongside it."
)


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
        await self._seed_default_routing(company_id=company.id)
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

    async def _seed_default_routing(self, *, company_id: uuid.UUID) -> None:
        """Somewhere for the first message to land.

        Without a queue and a rule pointing at it, an inbound conversation
        reaches nothing: routing records ``LEFT_UNROUTED`` — which the Inbox
        classifies *critical*, "it reached no queue at all, so nothing will
        pick it up" — and the conversation sits where no agent is looking.

        That was the state every new company started in. Registration created
        the company, the owner and the roles, and onboarding walked the
        administrator through team, channels and ERP without ever mentioning
        that a queue was required. They finished setup believing they were
        live, and found out otherwise when a real customer messaged them.

        A catch-all rule rather than a narrow one: the point is that nothing
        falls through on day one. An administrator who wants conversations
        split by channel, language or keyword edits this rule or adds a
        higher-priority one above it — which is a change to a working system
        rather than the difference between working and not.
        """
        queue = Queue(
            company_id=company_id,
            name=DEFAULT_QUEUE_NAME,
            description=DEFAULT_QUEUE_DESCRIPTION,
        )
        # Through the session rather than a repository: this runs inside
        # registration's own transaction, and injecting two more
        # collaborators to write two rows would grow a constructor the
        # start-up wiring guard then has to know about.
        self._session.add(queue)
        await self._session.flush()
        self._session.add(
            RoutingRule(
                company_id=company_id,
                # The lowest precedence there is: every rule an administrator
                # writes later outranks it, so this catches what nothing else
                # claimed rather than competing with real routing.
                priority=DEFAULT_RULE_PRIORITY,
                conditions={},
                target_queue_id=queue.id,
            )
        )
        await self._seed_default_service(company_id=company_id, queue=queue)

    async def _seed_default_service(self, *, company_id: uuid.UUID, queue: Queue) -> None:
        """The company's first Service, and the chain is complete.

        **Company → Service → Queue → catch-all rule.** A company registered
        from here on is service-first from its first second: its SLA targets
        and AI policy come from a Service it owns rather than from platform
        fallbacks, and the Services screen shows something real the day they
        open it instead of an empty directory they have to guess at.

        Deliberately carries the *service* defaults rather than the platform
        ones. ``AiPolicy.pickup_delay_seconds`` is thirty seconds, so a new
        company's AI genuinely is a queue worker — it waits, visibly, and an
        agent gets first refusal. That is the promise the product makes, and
        until a Service existed there was nowhere for it to be true.

        **AI is enabled on the service, and still off everywhere it was.**
        Two switches already gate it and both default off — the company's
        Autopilot setting, which ``Policy.AI_ENGAGEMENT`` checks *before* it
        reaches the service, and the queue's own opt-in. Neither moves here,
        so a new company's AI is silent until somebody turns it on. Safe by
        default, exactly as before.

        Seeding the service's switch off as well would look equally safe and
        be a trap: it adds a *third* gate, on the one screen a new
        administrator has no reason to open, and turning on the two they know
        about would leave AI silent with the explanation only in a routing
        decision row. A service somebody *creates* defaults to AI off,
        because creating one is a deliberate choice about a line of business.
        This one is chosen by nobody, so it must not decide anything on their
        behalf — it says this company's work *may* use AI, and the switches
        they already know about still say whether it does.

        Stage 2 seeds existing companies from their *effective* configuration
        instead, which is the same principle reaching the opposite value: a
        company that has already made its choices must keep them, and one
        that has made none must not have any invented for it. See
        ``docs/architecture/service-centric-migration.md``.

        Named as the company default so ``FallbackStage`` resolves to it
        explicitly rather than to whichever service happens to sort first —
        the same reason Stage 2 sets one.
        """
        service = Service(
            company_id=company_id,
            code=DEFAULT_SERVICE_CODE,
            name=DEFAULT_SERVICE_NAME,
            description=DEFAULT_SERVICE_DESCRIPTION,
        )
        self._session.add(service)
        await self._session.flush()

        policy = AiPolicy()
        self._session.add(
            ServiceVersion(
                service_id=service.id,
                company_id=company_id,
                version=1,
                name=DEFAULT_SERVICE_NAME,
                logical_queue_id=queue.id,
                logical_queue_name=queue.name,
                # Not ``policy.enabled`` — see the docstring. The company's
                # own switches sit above this one and are what decides.
                ai_enabled=True,
                ai_pickup_delay_seconds=policy.pickup_delay_seconds,
                # ``ai_resume_delay_seconds`` is deliberately left to the
                # column default. Nothing in the platform consults it — see
                # ``test_nothing_reads_the_ai_resume_delay`` — so writing it
                # here would put a figure on the Services screen that reads
                # like a promise and is not one. The stored row is identical
                # either way; what differs is whether the seed asserts a
                # behaviour that does not exist.
                change_note="Created with the company",
            )
        )
        await self._session.flush()
        service.current_version_id = (
            (
                await self._session.execute(
                    select(ServiceVersion.id).where(ServiceVersion.service_id == service.id)
                )
            )
            .scalars()
            .first()
        )

        company = await self._companies.get_by_id(company_id)
        if company is not None:
            settings = dict(company.settings or {})
            settings["services"] = {
                **(settings.get("services") or {}),
                "default_service_id": str(service.id),
            }
            company.settings = settings

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
