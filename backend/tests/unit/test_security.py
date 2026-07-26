import re
from uuid import uuid4

import pytest

from blinkengage.api.schemas.validators import validate_password_strength
from blinkengage.core.config import get_settings
from blinkengage.core.security import (
    InvalidTokenError,
    TokenType,
    create_token,
    decode_token,
    generate_temporary_password,
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

    token, jti = create_token(subject=subject, settings=settings, token_type=TokenType.ACCESS)
    payload = decode_token(token, settings=settings, expected_type=TokenType.ACCESS)

    assert payload["sub"] == str(subject)
    assert payload["type"] == TokenType.ACCESS.value
    assert payload["jti"] == jti


def test_create_token_issues_unique_jti_per_call() -> None:
    settings = get_settings()
    subject = uuid4()

    _, jti_one = create_token(subject=subject, settings=settings, token_type=TokenType.REFRESH)
    _, jti_two = create_token(subject=subject, settings=settings, token_type=TokenType.REFRESH)

    assert jti_one != jti_two


def test_decode_token_rejects_wrong_token_type() -> None:
    settings = get_settings()
    token, _ = create_token(subject=uuid4(), settings=settings, token_type=TokenType.REFRESH)

    with pytest.raises(InvalidTokenError):
        decode_token(token, settings=settings, expected_type=TokenType.ACCESS)


def test_decode_token_rejects_tampered_token() -> None:
    settings = get_settings()
    token, _ = create_token(subject=uuid4(), settings=settings, token_type=TokenType.ACCESS)

    with pytest.raises(InvalidTokenError):
        decode_token(token + "tampered", settings=settings, expected_type=TokenType.ACCESS)


def test_generate_temporary_password_always_passes_strength_validation() -> None:
    # Run many times — the letter/digit guarantee must hold every time,
    # not just probabilistically.
    for _ in range(200):
        password = generate_temporary_password()
        validate_password_strength(password)  # raises if it doesn't pass


def test_generate_temporary_password_respects_requested_length() -> None:
    assert len(generate_temporary_password(24)) == 24


def test_generate_temporary_password_produces_unique_values() -> None:
    passwords = {generate_temporary_password() for _ in range(50)}
    assert len(passwords) == 50


def test_generate_temporary_password_rejects_too_short_a_length() -> None:
    with pytest.raises(ValueError):
        generate_temporary_password(1)


def test_generate_temporary_password_only_uses_letters_and_digits() -> None:
    password = generate_temporary_password()
    assert re.fullmatch(r"[A-Za-z0-9]+", password)
