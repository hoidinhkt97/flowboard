"""Auth primitives: password hashing, JWT, opaque token gen/hash, and
Fernet encryption for per-user secrets."""
from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone

import jwt
from cryptography.fernet import Fernet
from passlib.context import CryptContext

from flowboard.config import (
    ACCESS_TOKEN_TTL_MIN,
    ENCRYPTION_KEY,
    JWT_ALG,
    JWT_SECRET,
)

_pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Dev/test fallback so encryption round-trips without a configured key.
# Production MUST set FLOWBOARD_ENCRYPTION_KEY to a real Fernet key.
_DEV_FERNET_KEY = b"ZmtkZXZrZXlfZmtkZXZrZXlfZmtkZXZrZXlfZmtkZXY="
_fernet = Fernet((ENCRYPTION_KEY.encode() if ENCRYPTION_KEY else _DEV_FERNET_KEY))


def hash_password(plaintext: str) -> str:
    return _pwd.hash(plaintext)


def verify_password(plaintext: str, hashed: str) -> bool:
    return _pwd.verify(plaintext, hashed)


def create_access_token(account_id: int) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(account_id),
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=ACCESS_TOKEN_TTL_MIN)).timestamp()),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALG)


def decode_access_token(token: str) -> dict:
    return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALG])


def generate_token() -> str:
    """Opaque, URL-safe random token (refresh + device tokens)."""
    return secrets.token_urlsafe(32)


def hash_token(raw: str) -> str:
    """Stable sha256 hex digest stored in place of the raw token."""
    return hashlib.sha256(raw.encode()).hexdigest()


def encrypt_secret(plaintext: str) -> bytes:
    return _fernet.encrypt(plaintext.encode())


def decrypt_secret(blob: bytes) -> str:
    return _fernet.decrypt(blob).decode()
