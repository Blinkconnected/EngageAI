"""AES-256-GCM encryption for secrets-at-rest (e.g. channel provider
credentials — see ``docs/architecture/channels.md``).

The key is derived (SHA-256) from ``settings.credentials_encryption_key``
— the same "long random string from settings" pattern already used for
``jwt_secret_key``. Swapping this for a real secrets manager (Vault/AWS
KMS) later is a one-function change (``_derive_key``), not a call-site or
schema change.
"""

import os

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from blinkengage.core.config import Settings

_NONCE_SIZE = 12


def _derive_key(settings: Settings) -> bytes:
    digest = hashes.Hash(hashes.SHA256())
    digest.update(settings.credentials_encryption_key.encode("utf-8"))
    return digest.finalize()


def encrypt(plaintext: bytes, *, settings: Settings) -> bytes:
    """Returns ``nonce || ciphertext`` — the nonce is not secret, only
    ever used once per encryption, and must travel with the ciphertext to
    decrypt it."""
    key = _derive_key(settings)
    nonce = os.urandom(_NONCE_SIZE)
    ciphertext = AESGCM(key).encrypt(nonce, plaintext, None)
    return nonce + ciphertext


def decrypt(blob: bytes, *, settings: Settings) -> bytes:
    key = _derive_key(settings)
    nonce, ciphertext = blob[:_NONCE_SIZE], blob[_NONCE_SIZE:]
    return AESGCM(key).decrypt(nonce, ciphertext, None)
