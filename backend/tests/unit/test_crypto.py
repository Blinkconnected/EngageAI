from blinkengage.core.config import get_settings
from blinkengage.infrastructure.security.crypto import decrypt, encrypt


def test_encrypt_decrypt_round_trips() -> None:
    settings = get_settings()
    plaintext = b'{"api_key": "super-secret-token"}'

    ciphertext = encrypt(plaintext, settings=settings)

    assert ciphertext != plaintext
    assert decrypt(ciphertext, settings=settings) == plaintext


def test_encrypt_is_not_deterministic() -> None:
    """Different nonces each call — same plaintext must not produce the
    same ciphertext twice, or an attacker could spot repeated secrets."""
    settings = get_settings()
    plaintext = b"same-value"

    first = encrypt(plaintext, settings=settings)
    second = encrypt(plaintext, settings=settings)

    assert first != second
    assert decrypt(first, settings=settings) == plaintext
    assert decrypt(second, settings=settings) == plaintext
