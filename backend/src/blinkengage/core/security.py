"""Password hashing and JWT token issuance/verification."""

from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from jose import JWTError, jwt
from passlib.context import CryptContext

from blinkengage.core.config import Settings

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


class TokenType(StrEnum):
    ACCESS = "access"
    REFRESH = "refresh"


class InvalidTokenError(Exception):
    """Raised when a JWT is malformed, expired, or of the wrong type."""


def hash_password(plain_password: str) -> str:
    return str(_pwd_context.hash(plain_password))


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return bool(_pwd_context.verify(plain_password, hashed_password))


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
    else:
        expire = now + timedelta(days=settings.refresh_token_expire_days)

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
