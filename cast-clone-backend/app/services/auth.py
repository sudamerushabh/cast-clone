"""Authentication utilities — password hashing and JWT token management."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import bcrypt
from jose import JWTError, jwt

ALGORITHM = "HS256"


def hash_password(password: str) -> str:
    password_bytes = password.encode("utf-8")
    hashed = bcrypt.hashpw(password_bytes, bcrypt.gensalt())
    return hashed.decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return bcrypt.checkpw(
        plain_password.encode("utf-8"),
        hashed_password.encode("utf-8"),
    )


def create_access_token(
    subject: str,
    secret_key: str,
    expires_hours: int = 24,
) -> str:
    expire = datetime.now(timezone.utc) + timedelta(hours=expires_hours)
    payload = {"sub": subject, "exp": expire}
    return jwt.encode(payload, secret_key, algorithm=ALGORITHM)


def decode_access_token(token: str, secret_key: str) -> str | None:
    try:
        payload = jwt.decode(token, secret_key, algorithms=[ALGORITHM])
        return payload.get("sub")
    except JWTError:
        return None
