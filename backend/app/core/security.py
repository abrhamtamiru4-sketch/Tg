"""
Security utilities.

Covers:
- JWT access/refresh token creation and validation
- Password hashing (bcrypt)
- Webhook secret validation
- Callback data HMAC signing
- CSRF token helpers
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.core.config import settings
from app.core.exceptions import AuthenticationError

_pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")

# ── Passwords ─────────────────────────────────────────────────

def hash_password(plain: str) -> str:
    return _pwd_ctx.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    return _pwd_ctx.verify(plain, hashed)


# ── JWT ───────────────────────────────────────────────────────

def _utc_now() -> datetime:
    return datetime.now(tz=timezone.utc)


def create_access_token(subject: str | int, extra: dict | None = None) -> str:
    expire = _utc_now() + timedelta(minutes=settings.access_token_expire_minutes)
    payload: dict[str, Any] = {
        "sub": str(subject),
        "exp": expire,
        "iat": _utc_now(),
        "type": "access",
    }
    if extra:
        payload.update(extra)
    return jwt.encode(payload, settings.secret_key, algorithm=settings.jwt_algorithm)


def create_refresh_token(subject: str | int) -> str:
    expire = _utc_now() + timedelta(days=settings.refresh_token_expire_days)
    payload = {
        "sub": str(subject),
        "exp": expire,
        "iat": _utc_now(),
        "type": "refresh",
        "jti": secrets.token_hex(16),
    }
    return jwt.encode(payload, settings.secret_key, algorithm=settings.jwt_algorithm)


def decode_token(token: str, expected_type: str = "access") -> dict[str, Any]:
    """Decode and validate a JWT. Returns the payload."""
    try:
        payload = jwt.decode(
            token,
            settings.secret_key,
            algorithms=[settings.jwt_algorithm],
        )
    except JWTError as exc:
        raise AuthenticationError(f"Invalid token: {exc}") from exc

    if payload.get("type") != expected_type:
        raise AuthenticationError(f"Expected '{expected_type}' token, got '{payload.get('type')}'")

    return payload


# ── Webhook secret validation ─────────────────────────────────

def validate_webhook_secret(header_value: str) -> bool:
    """
    Validate the X-Telegram-Bot-Api-Secret-Token header.
    Uses constant-time comparison to prevent timing attacks.
    """
    if not settings.webhook_secret:
        return True  # No secret configured → accept all (dev mode)
    return hmac.compare_digest(
        header_value.encode(),
        settings.webhook_secret.encode(),
    )


# ── Callback data signing ─────────────────────────────────────

def sign_callback_data(data: str) -> str:
    """
    Append an HMAC signature to callback data to prevent tampering.
    Format: "<data>|<sig>"
    """
    sig = hmac.new(
        settings.secret_key.encode(),
        data.encode(),
        hashlib.sha256,
    ).hexdigest()[:12]
    return f"{data}|{sig}"


def verify_callback_data(signed: str) -> str:
    """
    Verify and strip the signature from callback data.
    Returns the original data string.
    """
    if "|" not in signed:
        raise AuthenticationError("Callback data is not signed")
    data, sig = signed.rsplit("|", 1)
    expected_sig = hmac.new(
        settings.secret_key.encode(),
        data.encode(),
        hashlib.sha256,
    ).hexdigest()[:12]
    if not hmac.compare_digest(sig.encode(), expected_sig.encode()):
        raise AuthenticationError("Callback data signature invalid")
    return data


# ── CSRF ──────────────────────────────────────────────────────

def generate_csrf_token() -> str:
    return secrets.token_urlsafe(32)


def verify_csrf_token(submitted: str, stored: str) -> bool:
    return hmac.compare_digest(submitted.encode(), stored.encode())


# ── Idempotency keys ─────────────────────────────────────────

def make_idempotency_key(post_id: int, channel_id: int, scheduled_at: float | None = None) -> str:
    """
    Deterministic idempotency key for a publish job.
    The same (post, channel, schedule) combination always returns the same key,
    preventing accidental duplicate publishing.
    """
    ts = int(scheduled_at) if scheduled_at else int(time.time() // 60)  # 1-minute bucket
    raw = f"publish:{post_id}:{channel_id}:{ts}"
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


# ── API keys ─────────────────────────────────────────────────

def generate_api_key() -> tuple[str, str]:
    """
    Generate a (raw_key, hashed_key) pair.
    Store only hashed_key in the database; return raw_key to the user once.
    """
    raw = "tp_" + secrets.token_urlsafe(40)
    hashed = hashlib.sha256(raw.encode()).hexdigest()
    return raw, hashed


def verify_api_key(raw: str, hashed: str) -> bool:
    candidate = hashlib.sha256(raw.encode()).hexdigest()
    return hmac.compare_digest(candidate, hashed)
