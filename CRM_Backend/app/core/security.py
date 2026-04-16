from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from jose import JWTError, jwt

from app.core.config import get_settings

_ITERATIONS = 480_000
_HASH_ALGO = "sha256"
_SALT_BYTES = 32


def generate_salt() -> str:
    return secrets.token_hex(_SALT_BYTES)


def hash_password(password: str, salt: str) -> str:
    dk = hashlib.pbkdf2_hmac(
        _HASH_ALGO,
        password.encode("utf-8"),
        salt.encode("utf-8"),
        _ITERATIONS,
    )
    return dk.hex()


def verify_password(password: str, salt: str, stored_hash: str) -> bool:
    calculated = hash_password(password, salt)
    return secrets.compare_digest(calculated, stored_hash)


def create_access_token(subject: str, expires_minutes: Optional[int] = None) -> str:
    settings = get_settings()
    minutes = expires_minutes or settings.jwt_access_token_expire_minutes
    expire = datetime.now(timezone.utc) + timedelta(minutes=minutes)

    payload: dict[str, Any] = {
        "sub": subject,
        "exp": expire,
    }

    return jwt.encode(
        payload,
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )


def decode_token(token: str) -> dict[str, Any] | None:
    settings = get_settings()
    try:
        return jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
        )
    except JWTError:
        return None