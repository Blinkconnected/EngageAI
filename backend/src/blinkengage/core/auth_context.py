"""The authenticated-request context derived from a validated access token.

Permission codes are embedded in the access token at issuance time (see
``application.services.auth_service.AuthService.issue_tokens``) so
authorization checks don't need a database round-trip on every request.

Tradeoff: a permission or role change takes effect for an already-issued
access token only once it expires (``ACCESS_TOKEN_EXPIRE_MINUTES``,
15 minutes by default) or the client refreshes. This is an explicit,
documented latency window — see docs/architecture/backend.md. Anything
that must take effect immediately (e.g. deactivating a compromised
account) should also revoke the account's refresh tokens
(``RefreshTokenStore.revoke_all_for_user``) so re-authentication fails
even before the access token expires.
"""

from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True, slots=True)
class AuthContext:
    user_id: UUID
    company_id: UUID
    permissions: frozenset[str]

    def has_permission(self, code: str) -> bool:
        return code in self.permissions


@dataclass(frozen=True, slots=True)
class PlatformContext:
    """A platform (super) administrator — an operator of the whole
    installation, belonging to no tenant.

    Deliberately a *separate* type from ``AuthContext`` rather than an
    ``AuthContext`` with a nullable ``company_id``. Every tenant endpoint
    reads ``auth.company_id`` and passes it straight into a repository
    filter; if that field could be ``None``, a single missed check would
    silently widen a query to every company. Keeping the two principals
    as distinct types means a platform token simply cannot be passed to a
    tenant endpoint — ``get_current_auth`` rejects it outright — and the
    type checker enforces that, rather than a runtime convention.

    Note there is no ``permissions`` set: platform authority is
    all-or-nothing and lives outside the tenant RBAC catalog entirely, so
    no tenant role can ever be edited into it.
    """

    user_id: UUID
    #: True when this operator may read but not change. See
    #: ``User.platform_read_only`` — it only narrows authority, never
    #: widens it.
    read_only: bool = False
