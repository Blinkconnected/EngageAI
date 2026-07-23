from uuid import uuid4

import pytest

from blinkengage.core.config import get_settings
from blinkengage.core.security import (
    InvalidTokenError,
    TokenType,
    create_token,
    decode_token,
    hash_password,
    verify_password,
)


def test_hash_password_produces_verifiable_hash() -> None:
    hashed = hash_password("correct-horse-battery-staple")
    assert hashed != "correct-horse-battery-staple"
    assert verify_password("correct-horse-battery-staple", hashed)


def test_verify_password_rejects_wrong_password() -> None:
    hashed = hash_password("correct-horse-battery-staple")
    assert not verify_password("wrong-password", hashed)


def test_create_and_decode_access_token_roundtrip() -> None:
    settings = get_settings()
    subject = uuid4()

    token = create_token(subject=subject, settings=settings, token_type=TokenType.ACCESS)
    payload = decode_token(token, settings=settings, expected_type=TokenType.ACCESS)

    assert payload["sub"] == str(subject)
    assert payload["type"] == TokenType.ACCESS.value


def test_decode_token_rejects_wrong_token_type() -> None:
    settings = get_settings()
    token = create_token(subject=uuid4(), settings=settings, token_type=TokenType.REFRESH)

    with pytest.raises(InvalidTokenError):
        decode_token(token, settings=settings, expected_type=TokenType.ACCESS)


def test_decode_token_rejects_tampered_token() -> None:
    settings = get_settings()
    token = create_token(subject=uuid4(), settings=settings, token_type=TokenType.ACCESS)

    with pytest.raises(InvalidTokenError):
        decode_token(token + "tampered", settings=settings, expected_type=TokenType.ACCESS)
