"""Password accounts: scrypt password hashes and HMAC-signed login tokens (both stdlib).

A token is "<user_id>.<expiry unix s>.<signature>". It's stateless: logging out drops the token
client-side, and changing AUTH_SECRET signs everyone out.
"""

import base64
import hashlib
import hmac
import secrets
import time
import uuid

from app.config import Settings

_N, _R, _P = 2**14, 8, 1


class AuthNotConfigured(RuntimeError):
    pass


class InvalidToken(ValueError):
    pass


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=_N, r=_R, p=_P)
    return f"scrypt${_N}${_R}${_P}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str | None) -> bool:
    try:
        algo, n, r, p, salt, digest = (stored or "").split("$")
    except ValueError:
        return False
    if algo != "scrypt":
        return False
    candidate = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=int(n), r=int(r), p=int(p))
    return hmac.compare_digest(candidate.hex(), digest)


def _secret(settings: Settings) -> bytes:
    if not settings.auth_secret:
        raise AuthNotConfigured("Sign-in isn't set up on this server (AUTH_SECRET is empty)")
    return settings.auth_secret.encode()


def _sign(settings: Settings, payload: str) -> str:
    mac = hmac.new(_secret(settings), payload.encode(), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(mac).decode().rstrip("=")


def make_token(settings: Settings, user_id: uuid.UUID, now: float | None = None) -> tuple[str, int]:
    expires = int((now or time.time()) + settings.auth_token_ttl_days * 86400)
    payload = f"{user_id}.{expires}"
    return f"{payload}.{_sign(settings, payload)}", expires


def read_token(settings: Settings, token: str, now: float | None = None) -> uuid.UUID:
    try:
        uid, expires, sig = token.split(".")
        user_id = uuid.UUID(uid)
        exp = int(expires)
    except ValueError as e:
        raise InvalidToken("Malformed token") from e
    if not hmac.compare_digest(sig, _sign(settings, f"{uid}.{expires}")):
        raise InvalidToken("Invalid token")
    if exp < (now or time.time()):
        raise InvalidToken("Session expired, sign in again")
    return user_id


def is_dev_email(settings: Settings, email: str | None) -> bool:
    return bool(email) and email.lower() in settings.dev_emails
