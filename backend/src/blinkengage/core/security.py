"""Password hashing and JWT token issuance/verification."""

import secrets
import string
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from jose import JWTError, jwt
from passlib.context import CryptContext

from blinkengage.core.config import Settings

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

_TEMP_PASSWORD_LETTERS = string.ascii_letters
_TEMP_PASSWORD_DIGITS = string.digits
_TEMP_PASSWORD_ALPHABET = _TEMP_PASSWORD_LETTERS + _TEMP_PASSWORD_DIGITS


class TokenType(StrEnum):
    ACCESS = "access"
    REFRESH = "refresh"
    # A conversation-scoped, non-user token — see
    # docs/architecture/reports-analytics.md. Reuses this same JWT
    # machinery rather than a bespoke signing scheme; its "subject" is a
    # conversation id, not a user id.
    CSAT = "csat"


class InvalidTokenError(Exception):
    """Raised when a JWT is malformed, expired, or of the wrong type."""


def hash_password(plain_password: str) -> str:
    return str(_pwd_context.hash(plain_password))


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return bool(_pwd_context.verify(plain_password, hashed_password))


def generate_temporary_password(length: int = 16) -> str:
    """A cryptographically random password that always satisfies
    ``validate_password_strength`` (at least one letter, at least one
    digit) — used for e.g. inviting an agent by email, where nobody
    types a password in advance. Built from ``secrets.choice`` rather
    than ``secrets.token_urlsafe`` so the letter/digit guarantee is
    exact, not probabilistic: one random letter and one random digit are
    placed first, the rest is drawn from the full alphabet, then the
    whole string is shuffled so the guaranteed characters aren't always
    in the same position."""
    if length < 2:
        raise ValueError("length must be at least 2")
    chars = [
        secrets.choice(_TEMP_PASSWORD_LETTERS),
        secrets.choice(_TEMP_PASSWORD_DIGITS),
        *(secrets.choice(_TEMP_PASSWORD_ALPHABET) for _ in range(length - 2)),
    ]
    for i in range(len(chars) - 1, 0, -1):
        j = secrets.randbelow(i + 1)
        chars[i], chars[j] = chars[j], chars[i]
    return "".join(chars)


def create_token(
    *,
    subject: UUID,
    settings: Settings,
    token_type: TokenType,
    extra_claims: dict[str, Any] | None = None,
) -> tuple[str, str]:
    """Issue a JWT. Returns ``(token, jti)`` — every token carries a unique
    ``jti`` claim so refresh tokens can be tracked/revoked individually.
    """
    now = datetime.now(UTC)
    if token_type is TokenType.ACCESS:
        expire = now + timedelta(minutes=settings.access_token_expire_minutes)
    elif token_type is TokenType.REFRESH:
        expire = now + timedelta(days=settings.refresh_token_expire_days)
    else:
        expire = now + timedelta(days=settings.csat_token_expire_days)

    jti = str(uuid4())
    payload: dict[str, Any] = {
        "sub": str(subject),
        "type": token_type.value,
        "jti": jti,
        "iat": int(now.timestamp()),
        "exp": int(expire.timestamp()),
    }
    if extra_claims:
        payload.update(extra_claims)

    token = str(jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm))
    return token, jti


def decode_token(
    token: str,
    *,
    settings: Settings,
    expected_type: TokenType,
) -> dict[str, Any]:
    try:
        payload: dict[str, Any] = jwt.decode(
            token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm]
        )
    except JWTError as exc:
        raise InvalidTokenError("Token is invalid or expired") from exc

    if payload.get("type") != expected_type.value:
        raise InvalidTokenError(f"Expected a {expected_type.value} token")

    return payload
