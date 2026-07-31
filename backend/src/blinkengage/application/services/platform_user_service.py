"""Platform administration of a company's user accounts.

The operator tier can already list companies, toggle their entitlements
and suspend them (``platform_service.py``). This is that same tier acting
one level down — on the *accounts* inside a company, for the cases where
the customer's own administrator cannot: locked out, gone, or waiting on
a verification email that never arrived.

**The rule this file exists to uphold: an operator may restore access and
remove access, but never assume it.** Every operation below is
reversible by the customer and visible to them. What is deliberately
absent is the other half:

- no impersonation — it would hand the operator the tenant's
  conversations, which is precisely what the isolation promise in
  ``docs/architecture/platform-admin.md`` forbids;
- no setting a password to a value the operator knows — a link sent to
  the address already on the account is safe, choosing the secret is an
  account-takeover primitive;
- no changing an email address — change the address, then reset it, and
  the account belongs to whoever did it;
- no deleting users — the tenant does that themselves, and deactivation
  is the reversible operator equivalent;
- nothing that reads a conversation, a customer or a message.

Any of those added here would not be an extension of this feature; it
would end the promise the rest of the platform tier is built to keep.

**The company id comes from the path, so it is checked rather than
trusted.** Every other service in this codebase reads ``company_id`` off
the caller's own token. These endpoints take it from the URL — the
inversion the platform tier exists for — so every query filters on it
*and* every single-row lookup re-asserts that the row really belongs to
it. A user id from another tenant answers **404, never 403**:
distinguishing the two confirms that the id exists, which is itself a
leak across tenants.

The queries live here rather than in ``PlatformRepository`` because none
of them are unscoped. That repository holds the genuinely cross-tenant
reads (counts spanning every company, one file to audit); everything
below names exactly one company id.

**Every write publishes a domain event carrying the operator's reason.**
The audit-log consumer turns those into rows in the *tenant's own* audit
log, which the customer reads with ``audit_logs.read`` — so when platform
staff act on a customer's account, the customer can see it. ``company_id``
on the event is the tenant's, because that is whose account was acted on;
the operator has none of their own. Six months later that reason is the
only explanation anybody has for why platform staff touched a customer's
account, which is why an empty one is refused at the schema.
"""

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from blinkengage.application.services.verification_service import VerificationService
from blinkengage.domain.events import DomainEvent, DomainEventPublisher
from blinkengage.domain.exceptions import DomainError, EntityNotFoundError
from blinkengage.domain.rbac import SystemRole
from blinkengage.infrastructure.cache.refresh_tokens import RefreshTokenStore
from blinkengage.infrastructure.database.models.rbac import Role, UserRole
from blinkengage.infrastructure.database.models.user import User
from blinkengage.infrastructure.repositories.company_repository import CompanyRepository
from blinkengage.infrastructure.repositories.role_repository import RoleRepository
from blinkengage.infrastructure.repositories.user_repository import UserRepository

# These two live here, next to the only rules that raise them, rather
# than in `domain/exceptions/__init__.py` — the same local-to-its-domain
# placement `domain/ledger.py` and `domain/countries.py` already use.
# Both are plain `DomainError` subclasses, so `domain_error_handler`'s MRO
# walk maps them to 400 with their own message as the detail.


class CompanyOwnershipError(DomainError):
    """A change that would leave a company with nobody able to run it.

    A company whose owner is deactivated, demoted, or replaced by an
    account that cannot sign in is a company that can no longer add
    users, edit its own roles or manage its billing — and the one
    principal who could repair that from the inside is exactly the one
    that was just removed. The only remaining fix would be another
    platform intervention, so it is refused at the point of the mistake.

    The message always names the way out. "Not allowed" on its own leaves
    an operator to guess, and the guess is usually to try the same thing
    on a different account.
    """


class VerificationEmailNotSentError(DomainError):
    """A verification email was asked for and not sent.

    Distinct from a silent no-op: the operator pressed this button
    because a customer told them the message never arrived, and an
    answer of "done" when nothing was sent sends both of them to look at
    the customer's spam folder for an email that does not exist.
    """


@dataclass(frozen=True, slots=True)
class CompanyUserView:
    """One account as the console renders it: the user plus the single
    role they hold.

    Carried together because the role comes from a different table and
    the API layer must not issue its own query per row — see
    ``RoleRepository.get_role_for_user`` on why "one role per user" is
    the real invariant even though the schema permits more.
    """

    user: User
    role: Role | None


class PlatformUserService:
    def __init__(
        self,
        *,
        session: AsyncSession,
        companies: CompanyRepository,
        users: UserRepository,
        roles: RoleRepository,
        verification: VerificationService,
        refresh_tokens: RefreshTokenStore,
        events: DomainEventPublisher,
    ) -> None:
        self._session = session
        self._companies = companies
        self._users = users
        self._roles = roles
        self._verification = verification
        self._refresh_tokens = refresh_tokens
        self._events = events

    # --- reads -------------------------------------------------------

    async def list_users(self, *, company_id: UUID) -> tuple[list[CompanyUserView], int]:
        """Every account that belongs to one company, and nothing else.

        Three exclusions, each of which would be a bug if it leaked:

        - **another company's users**, by the ``company_id`` filter — the
          whole isolation model in one predicate;
        - **platform administrators**, who carry ``company_id IS NULL``
          and so are already excluded by that filter; asserted a second
          time anyway, because a platform account appearing in a
          customer's user list would also be *actionable* through the
          routes below, and one operator deactivating another is not a
          tenant-administration action;
        - **soft-deleted users**, who are gone as far as the product is
          concerned and whose email address has already been released for
          reuse (see ``docs/architecture/auth-rbac.md``).

        Unpaginated, like ``GET /roles``: a company's user list is a
        bounded administrative set, not a growing operational dataset.
        The count travels in the envelope so pagination can be added later
        without changing the response shape.
        """
        await self._require_company(company_id)
        users = (
            (
                await self._session.execute(
                    select(User)
                    .where(
                        User.company_id == company_id,
                        User.deleted_at.is_(None),
                        User.is_platform_admin.is_(False),
                    )
                    .order_by(User.full_name, User.email)
                )
            )
            .scalars()
            .all()
        )
        roles = await self._roles_by_user(company_id)
        views = [CompanyUserView(user=user, role=roles.get(user.id)) for user in users]
        return views, len(views)

    # --- writes ------------------------------------------------------

    async def set_active(
        self,
        *,
        company_id: UUID,
        user_id: UUID,
        is_active: bool,
        reason: str,
        actor_user_id: UUID,
    ) -> CompanyUserView:
        """Locks an account out, or lets it back in.

        Deactivation is the operator's *reversible* removal of access, and
        the reason it exists instead of deletion: a compromised or
        disputed account can be stopped now and restored intact later.

        **The company's last active owner cannot be deactivated.** The
        flag would survive — the company would still record an owner —
        but nobody could sign in as them, so nothing that needs
        ``roles.manage`` could ever be done again from inside the tenant.
        This is a different question from demoting an owner (see
        ``set_role``): there the account still works and it is the
        *permissions* that vanish, so that check is about the Owner role
        rather than about how many owners can still sign in.

        Refresh tokens are revoked on deactivation, matching
        ``AgentService.delete()``. ``AuthService.refresh`` would refuse
        them anyway once ``is_active`` is false — but leaving live
        allowlist entries behind means a later reactivation silently
        resurrects sessions issued *before* the lockout, and restoring
        access is not the same as restoring the sessions that were
        current when access was taken away. The access token already in
        the client's hands stays valid for its remaining lifetime (≤15
        minutes; the tradeoff ``auth-rbac.md`` documents and accepts).
        """
        user = await self._get_company_user(company_id=company_id, user_id=user_id)
        if not is_active and user.is_company_owner:
            await self._require_another_active_owner(
                company_id=company_id,
                excluding=user.id,
                remedy=(
                    "This is the only owner of this company who can still sign in. "
                    "Transfer ownership to another active user of the company first, "
                    "then deactivate this account."
                ),
            )

        previously_active = user.is_active
        user.is_active = is_active
        if not is_active:
            await self._refresh_tokens.revoke_all_for_user(user_id=user.id)
        await self._session.flush()

        await self._publish(
            event_type="platform.user_status_changed",
            company_id=company_id,
            user_id=user.id,
            actor_user_id=actor_user_id,
            reason=reason,
            payload={"previously_active": previously_active, "is_active": is_active},
        )
        return await self._view(company_id=company_id, user=user)

    async def resend_verification(
        self, *, company_id: UUID, user_id: UUID, reason: str, actor_user_id: UUID
    ) -> str:
        """Sends the email-verification message again, to the address
        already on the account.

        Delegates to ``VerificationService.resend`` rather than issuing a
        token here. There is one token issuer in this application and it
        stores only the hash; a second one written for the console would
        be a second chance to get that wrong, and the operator would
        become a party who has seen a live credential. Here the operator
        never sees the token and cannot choose the recipient.

        The two-minute throttle in that service is deliberately kept.
        Unthrottled, this route is a way to use the installation to mail
        an address somebody else owns — and a platform token is exactly
        the credential that must not turn into one.

        Returns the address it went to, so the console can show *which*
        inbox to check rather than implying the operator chose it.
        """
        user = await self._get_company_user(company_id=company_id, user_id=user_id)
        if user.email_verified_at is not None:
            raise VerificationEmailNotSentError(
                f"{user.email} is already verified, so there is nothing to confirm."
            )
        if not await self._verification.resend(user):
            # `resend` answers one boolean for two different situations and
            # this layer cannot tell them apart without re-implementing its
            # throttle query — which would be a second copy of the rule, and
            # the copy is what drifts. Both possibilities are named, because
            # they have different fixes and an operator can rule one out in
            # seconds.
            raise VerificationEmailNotSentError(
                f"No verification email was sent to {user.email}. Either one was "
                "already sent within the last two minutes, or the platform mail "
                "relay refused it. Wait a couple of minutes and try again; if it "
                "still fails, check the mail settings in Platform Settings."
            )

        await self._publish(
            event_type="platform.user_verification_resent",
            company_id=company_id,
            user_id=user.id,
            actor_user_id=actor_user_id,
            reason=reason,
            payload={"sent_to": user.email},
        )
        return user.email

    async def set_role(
        self,
        *,
        company_id: UUID,
        user_id: UUID,
        role_id: UUID,
        reason: str,
        actor_user_id: UUID,
    ) -> CompanyUserView:
        """Moves a user to one of their own company's roles.

        The role must belong to the same company as the user. Roles are
        per-company by schema (``roles.company_id`` is NOT NULL), so a
        role id from elsewhere is not a permission error but a
        nonexistent one from this caller's point of view — 404, like
        every other cross-tenant id here.

        **The company owner cannot be moved off the Owner role.** Owner
        is the one role guaranteed to hold the whole permission catalog,
        including ``roles.manage``; demote the owner and the only account
        that could grant it back is the account that just lost it. This
        holds however many owners are active, which is what makes it a
        different rule from ``set_active``'s: deactivating an owner takes
        away a *sign-in*, and another active owner covers for it, whereas
        demoting one takes away the *authority* and no count of owners
        replaces it. The way out is a transfer, which moves the flag and
        the role together.
        """
        user = await self._get_company_user(company_id=company_id, user_id=user_id)
        role = await self._roles.get_by_id(role_id)
        if role is None or role.company_id != company_id:
            raise EntityNotFoundError("Role", role_id)

        if user.is_company_owner and role.name != SystemRole.OWNER.value:
            raise CompanyOwnershipError(
                "The company owner holds the Owner role, the only one granted every "
                "permission — moving them off it would leave the company unable to "
                "manage its own roles. Transfer ownership to another user of this "
                "company first; that account can then change this one's role."
            )

        previous = await self._roles.get_role_for_user(company_id=company_id, user_id=user.id)
        await self._roles.replace_user_role(user_id=user.id, role_id=role.id)
        await self._publish(
            event_type="platform.user_role_changed",
            company_id=company_id,
            user_id=user.id,
            actor_user_id=actor_user_id,
            reason=reason,
            payload={
                "previous_role_id": str(previous.id) if previous is not None else None,
                "previous_role_name": previous.name if previous is not None else None,
                "role_id": str(role.id),
                "role_name": role.name,
            },
        )
        return CompanyUserView(user=user, role=role)

    async def transfer_ownership(
        self, *, company_id: UUID, user_id: UUID, reason: str, actor_user_id: UUID
    ) -> CompanyUserView:
        """Makes another user of the company its owner.

        There is deliberately no "remove the owner" operation — the only
        way to move ownership is to name who receives it, so "transferred
        away and left ownerless" is a state this API cannot express. The
        remaining guardrails are about the *recipient*: they must be a
        real, non-deleted, **active** user of this same company. Handing
        ownership to an account that cannot sign in produces exactly the
        ownerless company the previous sentence rules out, by a longer
        route.

        The recipient is also given the Owner role. Ownership without it
        is a company whose owner cannot manage its roles and whose only
        possible rescuer is themselves — a deadlock, and one this service
        would then refuse to unwind, since ``set_role`` will not move a
        company owner off Owner.

        The outgoing owner's own role is left exactly as it was.
        Stripping permissions from them is the tenant's decision, not the
        operator's, and it is a decision the tenant can now make: with the
        flag moved, ``set_role`` no longer protects that account.
        """
        new_owner = await self._get_company_user(company_id=company_id, user_id=user_id)
        if not new_owner.is_active:
            raise CompanyOwnershipError(
                f"{new_owner.email} is deactivated and cannot own this company — an "
                "owner who cannot sign in leaves nobody able to administer it. "
                "Reactivate the account first, then transfer ownership to it."
            )
        if new_owner.is_company_owner:
            raise CompanyOwnershipError(
                f"{new_owner.email} already owns this company. Name the user "
                "ownership should move to instead."
            )

        owner_role = await self._roles.get_by_name(
            company_id=company_id, name=SystemRole.OWNER.value
        )
        if owner_role is None:
            # Seeded for every company at creation and re-created by the
            # permission sync on every deploy, so its absence is a broken
            # installation rather than a caller's mistake — surfaced as a
            # missing entity instead of quietly transferring ownership to
            # an account that would hold no permissions at all.
            raise EntityNotFoundError("Role", SystemRole.OWNER.value)

        previous_owners = await self._owners(company_id)
        for previous_owner in previous_owners:
            previous_owner.is_company_owner = False
        new_owner.is_company_owner = True
        await self._roles.replace_user_role(user_id=new_owner.id, role_id=owner_role.id)
        await self._session.flush()

        await self._publish(
            event_type="platform.company_owner_transferred",
            company_id=company_id,
            user_id=new_owner.id,
            actor_user_id=actor_user_id,
            reason=reason,
            payload={
                "previous_owner_ids": [str(owner.id) for owner in previous_owners],
                "new_owner_id": str(new_owner.id),
                "new_owner_email": new_owner.email,
            },
        )
        return CompanyUserView(user=new_owner, role=owner_role)

    # --- scoping helpers ---------------------------------------------

    async def _require_company(self, company_id: UUID) -> None:
        """Refuses a company that does not exist or has been closed.

        Without it an unknown company id answers 200 with an empty list,
        which reads as "this customer has no users" rather than "no such
        customer" — and a closed company's accounts are not an operator's
        to administer.
        """
        company = await self._companies.get_by_id(company_id)
        if company is None or company.deleted_at is not None:
            raise EntityNotFoundError("Company", company_id)

    async def _get_company_user(self, *, company_id: UUID, user_id: UUID) -> User:
        """One user, proven to belong to the company named in the path.

        The single most important check in this file. Everything else here
        would happily act on any user row in the installation, because the
        id is supplied by the caller rather than derived from their token.

        Every failure — unknown id, another tenant's user, a soft-deleted
        one, a platform administrator — is the *same* 404. A 403 for
        "exists but is not yours" would answer, for any id an operator
        cares to try, whether that id exists.
        """
        await self._require_company(company_id)
        user = await self._users.get_by_id(user_id)
        if user is None or user.is_platform_admin or user.company_id != company_id:
            raise EntityNotFoundError("User", user_id)
        return user

    async def _require_another_active_owner(
        self, *, company_id: UUID, excluding: UUID, remedy: str
    ) -> None:
        remaining = (
            await self._session.execute(
                select(func.count())
                .select_from(User)
                .where(
                    User.company_id == company_id,
                    User.deleted_at.is_(None),
                    User.is_company_owner.is_(True),
                    User.is_active.is_(True),
                    User.id != excluding,
                )
            )
        ).scalar_one()
        if not remaining:
            raise CompanyOwnershipError(remedy)

    async def _owners(self, company_id: UUID) -> list[User]:
        return list(
            (
                await self._session.execute(
                    select(User).where(
                        User.company_id == company_id,
                        User.deleted_at.is_(None),
                        User.is_company_owner.is_(True),
                    )
                )
            )
            .scalars()
            .all()
        )

    async def _roles_by_user(self, company_id: UUID) -> dict[UUID, Role]:
        """Every company member's role in one query, so rendering N users
        costs one round trip rather than N — the same reasoning as
        ``RoleRepository.member_counts_for_company``."""
        rows = (
            await self._session.execute(
                select(UserRole.user_id, Role)
                .join(Role, Role.id == UserRole.role_id)
                .where(Role.company_id == company_id)
                .order_by(Role.name)
            )
        ).tuples()
        roles: dict[UUID, Role] = {}
        for user_id, role in rows:
            roles.setdefault(user_id, role)
        return roles

    async def _view(self, *, company_id: UUID, user: User) -> CompanyUserView:
        return CompanyUserView(
            user=user,
            role=await self._roles.get_role_for_user(company_id=company_id, user_id=user.id),
        )

    async def _publish(
        self,
        *,
        event_type: str,
        company_id: UUID,
        user_id: UUID,
        actor_user_id: UUID,
        reason: str,
        payload: dict[str, object],
    ) -> None:
        """One publisher for every write here, so no route can ship
        without an audit trail and none can ship without the reason.

        ``company_id`` is the **tenant's**, deliberately: a platform
        operator has none of their own, and the audit-log consumer skips
        any event without one — an accountability record the customer
        cannot read is not accountability.

        The operator is recorded **as values**, not only as
        ``actor_user_id``. That id belongs to a platform administrator,
        who is not a member of this company and does not appear in any
        list the tenant can read — so on their side it resolves to
        nothing, and the row says "somebody" did this. The same reasoning
        the financial audit trail already applies: an action has to stay
        attributable after the person who took it has left, and to a
        reader who never had access to them in the first place.

        ``by_platform_staff`` is the fact a customer most needs. "Our own
        administrator deactivated this account" and "the vendor did" are
        very different events, and nothing else on the row distinguishes
        them.
        """
        operator = await self._users.get_by_id(actor_user_id)
        await self._events.publish(
            DomainEvent(
                event_type=event_type,
                company_id=company_id,
                aggregate_type="user",
                aggregate_id=user_id,
                actor_user_id=actor_user_id,
                payload={
                    **payload,
                    "reason": reason,
                    "by_platform_staff": True,
                    "actor_email": operator.email if operator else None,
                    "actor_name": operator.full_name if operator else None,
                },
            )
        )


__all__ = [
    "CompanyOwnershipError",
    "CompanyUserView",
    "PlatformUserService",
    "VerificationEmailNotSentError",
]
