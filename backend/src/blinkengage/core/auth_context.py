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
