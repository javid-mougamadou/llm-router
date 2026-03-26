"""Minimal HMAC-SHA256 JWT — no external dependency."""

import base64
import hashlib
import hmac
import json
import time
from app.config import MASTER_KEY

_SECRET = MASTER_KEY.encode()
_TTL = 24 * 3600  # 24 hours


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _b64url_decode(s: str) -> bytes:
    pad = 4 - len(s) % 4
    return base64.urlsafe_b64decode(s + "=" * pad)


def _sign(payload: bytes) -> str:
    header = _b64url_encode(
        json.dumps({"alg": "HS256", "typ": "JWT"}).encode()
    )
    body = _b64url_encode(payload)
    sig_input = f"{header}.{body}".encode()
    sig = hmac.new(_SECRET, sig_input, hashlib.sha256).digest()
    return f"{header}.{body}.{_b64url_encode(sig)}"


def create_token(user_id: int, name: str) -> str:
    payload = json.dumps({
        "sub": user_id,
        "name": name,
        "iat": int(time.time()),
        "exp": int(time.time()) + _TTL,
    }).encode()
    return _sign(payload)


def verify_token(token: str) -> dict | None:
    """Return payload dict or None if invalid/expired."""
    try:
        parts = token.split(".")
        if len(parts) != 3:
            return None
        sig_input = f"{parts[0]}.{parts[1]}".encode()
        expected = hmac.new(
            _SECRET, sig_input, hashlib.sha256
        ).digest()
        actual = _b64url_decode(parts[2])
        if not hmac.compare_digest(expected, actual):
            return None
        payload = json.loads(_b64url_decode(parts[1]))
        if payload.get("exp", 0) < time.time():
            return None
        return payload
    except Exception:
        return None
