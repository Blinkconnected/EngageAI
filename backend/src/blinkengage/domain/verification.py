"""Email verification for a newly registered company.

See ``docs/architecture/company-onboarding.md``.

Framework-free, like the rest of ``domain/``.

Two decisions the rest of the implementation rests on.

**The token is stored as a hash, never in plaintext.** A verification
link is a bearer credential: anyone holding it can complete the
verification. A database backup, a log line or a support screenshot
containing the raw token is a way to verify somebody else's account, and
storing only the hash means the token exists in exactly one place — the
email that was sent.

**An unverified company can sign in.** It simply cannot do anything.
Refusing sign-in outright locks a customer out with nothing on screen to
act on when the email is delayed or bounces, and the only thing that
actually needs preventing is an unverified account *doing* something —
sending messages, connecting channels, inviting people.
"""

import secrets
from datetime import timedelta
from typing import Final

#: How long a verification link lives. Long enough to survive a mail
#: server queueing it overnight and somebody reading it the next
#: morning; short enough that a link forwarded or archived is not a
#: permanent credential.
TOKEN_LIFETIME: Final[timedelta] = timedelta(hours=48)

#: 32 bytes of entropy, URL-safe. Long enough that guessing is not a
#: strategy, short enough to survive an email client wrapping the line.
_TOKEN_BYTES: Final[int] = 32

#: How often a company may ask for another email. Resending is a
#: legitimate, common action — the first one lands in spam — but an
#: unthrottled resend endpoint is a way to use this installation to
#: send mail to an address somebody else owns.
RESEND_INTERVAL: Final[timedelta] = timedelta(minutes=2)


def generate_token() -> str:
    """A fresh verification token, for the email only."""
    return secrets.token_urlsafe(_TOKEN_BYTES)


#: What an unverified company is refused. Expressed as a set of
#: permission prefixes rather than a list of endpoints: an endpoint list
#: is a thing somebody forgets to add to, and the failure mode is a
#: feature that silently works before verification.
#:
#: Reading is deliberately allowed. Somebody who has just signed up
#: should be able to look around — the point is to stop an unverified
#: account *acting*, not to present them with an empty shell.
UNVERIFIED_BLOCKED_ACTIONS: Final[frozenset[str]] = frozenset(
    {
        "conversations.manage",
        "conversations.transfer",
        "conversations.pick",
        "conversations.release",
        "conversations.delete",
        "customers.manage",
        "channels.manage",
        "users.manage",
        "agents.manage",
        "workflows.manage",
        "knowledge_base.manage",
        "quick_replies.manage",
        "queues.manage",
        "teams.manage",
        "departments.manage",
        "roles.manage",
        "sla_policies.manage",
        "erp.manage",
        "ai.use",
    }
)


def is_blocked_before_verification(permission: str) -> bool:
    """Whether an unverified company is refused this action.

    Read at request time, not resolved once when routes are registered.
    A frozenset lookup costs nothing, and deciding per request means the
    rule can be reasoned about — and exercised — in one place rather
    than being baked into every route closure at import.
    """
    return permission in UNVERIFIED_BLOCKED_ACTIONS


__all__ = [
    "RESEND_INTERVAL",
    "TOKEN_LIFETIME",
    "UNVERIFIED_BLOCKED_ACTIONS",
    "generate_token",
    "is_blocked_before_verification",
]
