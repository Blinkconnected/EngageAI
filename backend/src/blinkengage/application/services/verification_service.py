"""Email verification for a newly registered company.

See ``docs/architecture/company-onboarding.md``.

Three operations: issue a token and mail it, consume one, and resend.

**The token is hashed on the way in and never stored raw.** A
verification link is a bearer credential — anyone holding it can
complete the verification — so the raw value exists in exactly one
place, the email that was sent. A database backup or a support
screenshot containing raw tokens would be a way to verify somebody
else's account.

**Verifying is idempotent from the customer's point of view.** Clicking
an already-used link says "already verified" rather than "invalid
link", because the second reads as though something went wrong when
nothing did.
"""

import hashlib
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from blinkengage.application.services.platform_settings_service import (
    PlatformSettingsService,
)
from blinkengage.core.config import Settings
from blinkengage.core.logging import get_logger
from blinkengage.domain.exceptions import EntityNotFoundError
from blinkengage.domain.verification import (
    RESEND_INTERVAL,
    TOKEN_LIFETIME,
    generate_token,
)
from blinkengage.infrastructure.database.models.company import Company
from blinkengage.infrastructure.database.models.user import User
from blinkengage.infrastructure.database.models.verification import (
    EmailVerificationToken,
)
from blinkengage.infrastructure.email.mailer import MailDeliveryError, send_with_config

logger = get_logger(__name__)


def hash_token(token: str) -> str:
    """SHA-256, hex.

    Not a password hash, and deliberately not bcrypt/argon2: this is a
    high-entropy random value, not something a human chose, so there is
    nothing for a slow hash to defend against — and a slow hash on the
    lookup path would mean scanning every row, because the digest is
    what the index is on.
    """
    return hashlib.sha256(token.encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class VerificationResult:
    """What happened, in terms the API can turn into a message.

    An enum-ish result rather than exceptions for the expected cases:
    "already verified" and "link expired" are normal things a customer
    does, not faults, and each needs its own sentence on screen.
    """

    verified: bool
    already_verified: bool = False
    expired: bool = False
    unknown: bool = False


class VerificationService:
    def __init__(
        self,
        *,
        session: AsyncSession,
        settings: Settings,
        platform_settings: PlatformSettingsService,
    ) -> None:
        self._session = session
        self._settings = settings
        self._platform_settings = platform_settings

    # --- issuing -----------------------------------------------------

    async def send_verification(self, user: User, *, company: Company) -> bool:
        """Issues a token and emails the link.

        Returns whether the mail was accepted by the relay. Registration
        does **not** fail when it was not: a customer whose account was
        created but whose email bounced can resend, whereas a rolled-back
        registration leaves them with nothing and an email address that
        now appears taken.
        """
        raw = generate_token()
        self._session.add(
            EmailVerificationToken(
                user_id=user.id,
                company_id=company.id,
                token_hash=hash_token(raw),
                expires_at=datetime.now(UTC) + TOKEN_LIFETIME,
            )
        )
        await self._session.flush()

        link = f"{self._settings.public_base_url.rstrip('/')}/verify-email?token={raw}"
        config = await self._platform_settings.mail_config()
        try:
            await send_with_config(
                config,
                to_address=user.email,
                subject="Confirm your email address",
                body=(
                    f"Hello {user.full_name},\n\n"
                    f"Confirm your email address to finish setting up {company.name}:\n\n"
                    f"{link}\n\n"
                    "This link is valid for 48 hours. If you did not create this "
                    "account, you can ignore this message.\n"
                ),
            )
        except MailDeliveryError as exc:
            # Logged without the token: a log line containing the raw
            # value would defeat storing only the hash.
            logger.warning("verification_email_failed", user_id=str(user.id), error=str(exc))
            return False
        return True

    async def resend(self, user: User) -> bool:
        """Sends another link, at most once every couple of minutes.

        Resending is legitimate and common — the first one lands in
        spam. Unthrottled, it is a way to use this installation to mail
        an address somebody else owns.
        """
        if user.email_verified_at is not None:
            return False

        recent = await self._session.execute(
            select(EmailVerificationToken.created_at)
            .where(
                EmailVerificationToken.user_id == user.id,
                EmailVerificationToken.created_at > datetime.now(UTC) - RESEND_INTERVAL,
            )
            .limit(1)
        )
        if recent.first() is not None:
            return False

        company = await self._session.get(Company, user.company_id)
        if company is None:
            raise EntityNotFoundError("Company", user.company_id)
        return await self.send_verification(user, company=company)

    # --- consuming ---------------------------------------------------

    async def verify(self, token: str) -> VerificationResult:
        """Consumes a verification link."""
        row = (
            await self._session.execute(
                select(EmailVerificationToken).where(
                    EmailVerificationToken.token_hash == hash_token(token)
                )
            )
        ).scalar_one_or_none()

        if row is None:
            return VerificationResult(verified=False, unknown=True)
        if row.consumed_at is not None:
            # Not an error. A customer who clicks the link twice, or
            # whose mail client prefetches it, has done nothing wrong.
            return VerificationResult(verified=True, already_verified=True)
        if row.expires_at <= datetime.now(UTC):
            return VerificationResult(verified=False, expired=True)

        now = datetime.now(UTC)
        # Guarded: two clicks arriving together must not both consume it.
        claimed = await self._session.execute(
            update(EmailVerificationToken)
            .where(
                EmailVerificationToken.id == row.id,
                EmailVerificationToken.consumed_at.is_(None),
            )
            .values(consumed_at=now)
        )
        if claimed.rowcount != 1:
            return VerificationResult(verified=True, already_verified=True)

        await self._session.execute(
            update(User).where(User.id == row.user_id).values(email_verified_at=now)
        )
        # The company is verified when its signup owner is. Both are
        # recorded: the user column is the fact (we proved this address
        # works), the company column is the gate (this workspace may
        # now act).
        await self._session.execute(
            update(Company)
            .where(Company.id == row.company_id, Company.verified_at.is_(None))
            .values(verified_at=now)
        )
        logger.info("email_verified", user_id=str(row.user_id))
        return VerificationResult(verified=True)

    async def is_verified(self, company_id: uuid.UUID) -> bool:
        company = await self._session.get(Company, company_id)
        return company is not None and company.verified_at is not None


__all__ = ["VerificationResult", "VerificationService", "hash_token"]
