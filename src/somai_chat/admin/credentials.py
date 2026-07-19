"""Opaque robot client Key generation and verification."""

import hashlib
import hmac
import secrets
from base64 import urlsafe_b64encode
from dataclasses import dataclass

from cryptography.fernet import Fernet

_KEY_PREFIX = "somai_sk"


@dataclass(frozen=True)
class KeyMaterial:
    key_id: str
    secret_digest: str


def create_key_material(pepper: str) -> tuple[str, KeyMaterial]:
    key_id = secrets.token_hex(8)
    secret = secrets.token_urlsafe(32)
    key = f"{_KEY_PREFIX}_{key_id}_{secret}"
    return key, KeyMaterial(key_id, _digest(key_id, secret, pepper))


def verify_key(key: str, key_id: str, secret_digest: str, pepper: str) -> bool:
    parts = key.split("_", 3)
    if len(parts) != 4 or "_".join(parts[:2]) != _KEY_PREFIX or parts[2] != key_id:
        return False
    return hmac.compare_digest(_digest(key_id, parts[3], pepper), secret_digest)


def encrypt_key(key: str, encryption_secret: str) -> str:
    return _fernet(encryption_secret).encrypt(key.encode()).decode()


def decrypt_key(encrypted_key: str, encryption_secret: str) -> str:
    return _fernet(encryption_secret).decrypt(encrypted_key.encode()).decode()


def _digest(key_id: str, secret: str, pepper: str) -> str:
    return hmac.new(pepper.encode(), f"{key_id}:{secret}".encode(), hashlib.sha256).hexdigest()


def _fernet(encryption_secret: str) -> Fernet:
    key = urlsafe_b64encode(hashlib.sha256(encryption_secret.encode()).digest())
    return Fernet(key)
