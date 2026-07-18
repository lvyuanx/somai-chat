"""Opaque robot client Key generation and verification."""

import hashlib
import hmac
import secrets
from dataclasses import dataclass

_KEY_PREFIX = "somai_sk"


@dataclass(frozen=True)
class KeyMaterial:
    key_id: str
    secret_digest: str


def create_key_material(pepper: str) -> tuple[str, KeyMaterial]:
    key_id = secrets.token_urlsafe(9)
    secret = secrets.token_urlsafe(32)
    key = f"{_KEY_PREFIX}_{key_id}_{secret}"
    return key, KeyMaterial(key_id, _digest(key_id, secret, pepper))


def verify_key(key: str, key_id: str, secret_digest: str, pepper: str) -> bool:
    parts = key.split("_", 3)
    if len(parts) != 4 or "_".join(parts[:2]) != _KEY_PREFIX or parts[2] != key_id:
        return False
    return hmac.compare_digest(_digest(key_id, parts[3], pepper), secret_digest)


def _digest(key_id: str, secret: str, pepper: str) -> str:
    return hmac.new(pepper.encode(), f"{key_id}:{secret}".encode(), hashlib.sha256).hexdigest()
