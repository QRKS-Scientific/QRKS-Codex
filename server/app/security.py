"""Password hashing (Argon2id) and tokens (signed access JWT + opaque rotating refresh token)."""
from __future__ import annotations

import hashlib
import hmac
import secrets
from typing import Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

from .config import Settings

TEMP_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"        # no 0/O or 1/I
MIN_PASSWORD_LENGTH = 10


def temp_password() -> str:
    raw = "".join(secrets.choice(TEMP_ALPHABET) for _ in range(12))
    return "-".join(raw[i:i + 4] for i in range(0, 12, 4))


def password_problem(new: str, current: str = "", initials: str = "") -> str | None:
    if len(new) < MIN_PASSWORD_LENGTH:
        return f"Use at least {MIN_PASSWORD_LENGTH} characters."
    if new == current:
        return "The new password must be different from the old one."
    if len(set(new)) < 4:
        return "Use a more varied password."
    if initials and initials.lower() in new.lower():
        return "Do not put your initials in your password."
    return None


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def new_refresh_token() -> str:
    return secrets.token_urlsafe(32)                      # 256 random bits


class Security:
    def __init__(self, s: Settings):
        self.s = s
        self.ph = PasswordHasher(time_cost=s.argon2_time_cost, memory_cost=s.argon2_memory_kib, parallelism=s.argon2_parallelism)
        self._dummy = self.ph.hash(self._prep("dummy-password-for-timing"))

    def _prep(self, password: str) -> str:
        if not self.s.pepper:
            return password
        return hmac.new(self.s.pepper.encode(), password.encode(), hashlib.sha256).hexdigest()

    def hash_password(self, password: str) -> str:
        return self.ph.hash(self._prep(password))

    def verify_password(self, stored: str, password: str) -> bool:
        try:
            return self.ph.verify(stored, self._prep(password))
        except (VerifyMismatchError, InvalidHashError):
            return False

    def dummy_verify(self, password: str) -> None:
        """Spend the same time as a real check, so an unknown account cannot be told apart by timing."""
        self.verify_password(self._dummy, password)

    # ---- access tokens ------------------------------------------------------------------------------------
    def access_token(self, initials: str, role: str, device_id: str, scope: str, now: float) -> tuple[str, int]:
        ttl = self.s.access_minutes * 60
        claims = {"sub": initials, "role": role, "did": device_id, "scope": scope, "iss": self.s.issuer,
                  "aud": self.s.audience, "iat": int(now), "exp": int(now) + ttl, "jti": secrets.token_hex(8)}
        return jwt.encode(claims, self.s.jwt_secret, algorithm="HS256"), ttl

    def decode_access(self, token: str, now: float) -> dict[str, Any]:
        """Verify signature, issuer and audience. Expiry is checked against our clock, not the machine's."""
        claims = jwt.decode(token, self.s.jwt_secret, algorithms=["HS256"], audience=self.s.audience,
                            issuer=self.s.issuer, options={"verify_exp": False, "require": ["exp", "sub", "did", "scope"]})
        if now >= claims["exp"]:
            raise jwt.ExpiredSignatureError("expired")
        return claims
