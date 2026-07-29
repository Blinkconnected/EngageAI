"""Email verification tokens.

See ``docs/architecture/company-onboarding.md``.

The token is stored **hashed**. A verification link is a bearer
credential, so a database backup or a support screenshot containing the
raw value is a way to verify somebody else's account; the raw token
exists only in the email that was sent.
"""

import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column

from blinkengage.infrastructure.database.base import (
    GUID,
    Base,
    UtcDateTime,
    UUIDPrimaryKeyMixin,
)


class EmailVerificationToken(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "email_verification_tokens"
    __table_args__ = (
        # The lookup on every verification attempt.
        Index("ix_email_verification_token_hash", "token_hash", unique=True),
        Index("ix_email_verification_user", "user_id"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False
    )

    token_hash: Mapped[str] = mapped_column(String(128), nullable=False)

    expires_at: Mapped[datetime] = mapped_column(UtcDateTime(), nullable=False)
    #: Set when the link is used. The row is kept rather than deleted, so
    #: a customer clicking the link twice can be told "already verified"
    #: instead of "invalid link", which reads like something went wrong.
    consumed_at: Mapped[datetime | None] = mapped_column(UtcDateTime(), default=None)

    created_at: Mapped[datetime] = mapped_column(
        UtcDateTime(), nullable=False, server_default=func.now()
    )


__all__ = ["EmailVerificationToken"]
