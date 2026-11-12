"""Shared request plumbing: database session, clock, rate limiting, and token checking."""
from __future__ import annotations

import time
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Callable, Iterator

import jwt
from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from .models import Device, User
from .security import Security


def fail(status: int, code: str, message: str, **extra) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "message": message, **extra})


def get_db(request: Request) -> Iterator[Session]:
    db = request.app.state.sessionmaker()
    try:
        yield db
    finally:
        db.close()


def get_settings(request: Request):
    return request.app.state.settings


def get_security(request: Request) -> Security:
    return request.app.state.security


def get_clock(request: Request) -> Callable[[], float]:
    return request.app.state.clock


def client_ip(request: Request) -> str:
    if request.app.state.settings.trust_proxy_headers:
        fwd = request.headers.get("x-forwarded-for", "")
        if fwd:
            return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


class RateLimiter:
    """Sliding one-minute window per (bucket, IP). In memory, which is right for a single-process server."""

    def __init__(self, clock: Callable[[], float] = time.time):
        self.clock = clock
        self.hits: dict[tuple[str, str], deque[float]] = defaultdict(deque)

    def check(self, bucket: str, key: str, limit: int, window: int = 60) -> None:
        now = self.clock()
        q = self.hits[(bucket, key)]
        while q and q[0] <= now - window:
            q.popleft()
        if len(q) >= limit:
            wait = max(1, int(q[0] + window - now) + 1)
            raise HTTPException(status_code=429, detail={"code": "rate_limited", "message": "Too many requests. Slow down and try again shortly.",
                                                          "retry_after": wait}, headers={"Retry-After": str(wait)})
        q.append(now)


def rate_limit_login(request: Request) -> None:
    s = request.app.state.settings
    request.app.state.limiter.check("login", client_ip(request), s.login_rate_per_minute)


def rate_limit_api(request: Request) -> None:
    s = request.app.state.settings
    request.app.state.limiter.check("api", client_ip(request), s.api_rate_per_minute)


@dataclass
class Principal:
    user: User
    device_id: str
    scope: str


def _principal(request: Request, db: Session, required: str) -> Principal:
    header = request.headers.get("authorization", "")
    if not header.lower().startswith("bearer "):
        raise fail(401, "not_authenticated", "Sign in first.")
    sec: Security = request.app.state.security
    try:
        claims = sec.decode_access(header[7:].strip(), request.app.state.clock())
    except jwt.ExpiredSignatureError:
        raise fail(401, "token_expired", "Your session token expired.")
    except jwt.PyJWTError:
        raise fail(401, "bad_token", "Invalid session token.")
    user = db.get(User, claims["sub"])
    if user is None or user.disabled:
        raise fail(401, "not_authenticated", "This account is not active.")
    dev = db.get(Device, (user.initials, claims["did"]))
    if dev is None or dev.revoked:
        raise fail(401, "device_revoked", "This laptop was signed out. Sign in again.")
    if required == "full" and claims["scope"] != "full":
        raise fail(403, "password_change_required", "Choose your own password before continuing.")
    return Principal(user, claims["did"], claims["scope"])


def require_full(request: Request, db: Session = Depends(get_db), _=Depends(rate_limit_api)) -> Principal:
    return _principal(request, db, "full")


def require_any(request: Request, db: Session = Depends(get_db), _=Depends(rate_limit_api)) -> Principal:
    return _principal(request, db, "any")
