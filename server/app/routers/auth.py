"""Sign-in and sessions.

Security properties (each one is covered by a test):
  * wrong passwords lock the account with a doubling delay; unknown accounts look identical to wrong passwords
  * a temporary password works until it is changed or expires, and never again afterwards
  * refresh tokens rotate on every use; replaying an old one revokes the whole session
  * a temporary-password session can do nothing except change the password
  * changing a password signs the account out everywhere else
"""
from __future__ import annotations

import math
import secrets
from typing import Callable

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from ..config import Settings
from ..deps import (Principal, client_ip, fail, get_clock, get_db, get_security, get_settings, rate_limit_api,
                    rate_limit_login, require_any)
from ..models import AuthEvent, Device, RefreshToken, User
from ..schemas import ChangePasswordIn, LoginIn, LogoutIn, RefreshIn
from ..security import Security, hash_token, new_refresh_token, password_problem

router = APIRouter(prefix="/v1/auth", tags=["auth"])


def audit(db: Session, now: float, request: Request, outcome: str, initials: str = "", device_id: str = "", detail: str = "") -> None:
    db.add(AuthEvent(utc=now, initials=initials, ip=client_ip(request), device_id=device_id, outcome=outcome, detail=detail[:200]))
    db.commit()


def issue_session(db: Session, sec: Security, s: Settings, user: User, device_id: str, scope: str, now: float,
                  family_id: str | None = None, absolute_expires: float | None = None) -> dict:
    """Create a refresh token (new family unless continuing one) and a matching access token."""
    family = family_id or secrets.token_hex(12)
    absolute = absolute_expires or now + s.refresh_absolute_days * 86400
    refresh = new_refresh_token()
    db.add(RefreshToken(family_id=family, initials=user.initials, device_id=device_id, token_hash=hash_token(refresh), status="active",
                        scope=scope, created_at=now, expires_at=min(now + s.refresh_idle_days * 86400, absolute), absolute_expires_at=absolute))
    db.commit()
    access, ttl = sec.access_token(user.initials, user.role, device_id, scope, now)
    return {"access_token": access, "refresh_token": refresh, "token_type": "bearer", "expires_in": ttl,
            "must_change": bool(user.must_change), "user": {"initials": user.initials, "display_name": user.display_name, "role": user.role}}


def revoke_family(db: Session, family_id: str) -> None:
    db.execute(update(RefreshToken).where(RefreshToken.family_id == family_id).values(status="revoked"))
    db.commit()


@router.post("/login")
def login(body: LoginIn, request: Request, db: Session = Depends(get_db), s: Settings = Depends(get_settings),
          sec: Security = Depends(get_security), clock: Callable[[], float] = Depends(get_clock), _=Depends(rate_limit_login)):
    now = clock()
    initials = body.initials.strip().upper()
    user = db.get(User, initials)
    if user is None:
        sec.dummy_verify(body.password)
        audit(db, now, request, "unknown_account", initials, body.device_id)
        raise fail(401, "bad_credentials", "Wrong initials or password.")
    if user.disabled:
        audit(db, now, request, "disabled", initials, body.device_id)
        raise fail(403, "account_disabled", "This account is disabled. Ask the Technical Lead.")
    if user.locked_until and user.locked_until > now:
        wait = math.ceil(user.locked_until - now)
        audit(db, now, request, "locked", initials, body.device_id)
        raise fail(423, "locked", f"Too many wrong passwords. Try again in {wait} s.", retry_after=wait)

    if not sec.verify_password(user.password_hash, body.password):
        user.failed_count += 1
        extra: dict = {}
        if user.failed_count >= s.lock_free_attempts:
            lock = min(s.lock_base_seconds * 2 ** (user.failed_count - s.lock_free_attempts), s.lock_max_seconds)
            user.locked_until = now + lock
            extra = {"retry_after": lock, "attempts_left": 0}
            message = f"Wrong password. This account is locked for {lock} s."
        else:
            left = s.lock_free_attempts - user.failed_count
            extra = {"attempts_left": left}
            message = f"Wrong password. {left} attempt{'s' if left != 1 else ''} left before a short lock."
        db.commit()
        audit(db, now, request, "bad_password", initials, body.device_id)
        raise fail(401, "bad_credentials", message, **extra)

    if user.must_change and user.temp_expires_at and now > user.temp_expires_at:
        audit(db, now, request, "temp_expired", initials, body.device_id)
        raise fail(403, "temp_expired", "The temporary password has expired. Ask the Technical Lead for a new one.")

    device = db.get(Device, (initials, body.device_id))
    if device is None:
        active = len(db.scalars(select(Device).where(Device.initials == initials, Device.revoked.is_(False))).all())
        if active >= s.max_devices:
            audit(db, now, request, "device_limit", initials, body.device_id)
            raise fail(409, "device_limit", f"This account is already used on {s.max_devices} laptops. Ask the Technical Lead to remove one.")
        device = Device(initials=initials, device_id=body.device_id, name=body.device_name, first_seen=now, last_seen=now)
        db.add(device)
    elif device.revoked:
        audit(db, now, request, "device_revoked", initials, body.device_id)
        raise fail(403, "device_revoked", "This laptop was removed from the account. Ask the Technical Lead.")
    device.last_seen, device.name = now, body.device_name or device.name

    user.failed_count, user.locked_until = 0, None
    db.commit()
    audit(db, now, request, "login_temp" if user.must_change else "login", initials, body.device_id)
    return issue_session(db, sec, s, user, body.device_id, "pwd_change" if user.must_change else "full", now)


@router.post("/refresh")
def refresh(body: RefreshIn, request: Request, db: Session = Depends(get_db), s: Settings = Depends(get_settings),
            sec: Security = Depends(get_security), clock: Callable[[], float] = Depends(get_clock), _=Depends(rate_limit_api)):
    now = clock()
    rt = db.scalar(select(RefreshToken).where(RefreshToken.token_hash == hash_token(body.refresh_token)))
    if rt is None:
        raise fail(401, "invalid_refresh", "Sign in again.")
    if rt.device_id != body.device_id:
        revoke_family(db, rt.family_id)
        audit(db, now, request, "refresh_wrong_device", rt.initials, body.device_id)
        raise fail(401, "session_revoked", "Sign in again.")
    if rt.status == "revoked":
        raise fail(401, "session_revoked", "Sign in again.")
    if rt.status == "used":
        # A replay. Within a few seconds it is most likely a lost response; later, it means the token leaked.
        if rt.used_at is None or now - rt.used_at > s.refresh_reuse_grace_seconds:
            revoke_family(db, rt.family_id)
            audit(db, now, request, "refresh_reuse", rt.initials, body.device_id, "old refresh token replayed; session revoked")
            raise fail(401, "session_revoked", "This session was ended for safety. Sign in again.")
    if now > rt.expires_at or now > rt.absolute_expires_at:
        revoke_family(db, rt.family_id)
        raise fail(401, "session_expired", "Your session expired. Sign in again.")
    user = db.get(User, rt.initials)
    device = db.get(Device, (rt.initials, rt.device_id))
    if user is None or user.disabled or device is None or device.revoked:
        revoke_family(db, rt.family_id)
        raise fail(401, "session_revoked", "Sign in again.")
    if rt.status == "active":
        rt.status, rt.used_at = "used", now
    device.last_seen = now
    db.commit()
    return issue_session(db, sec, s, user, rt.device_id, rt.scope, now, family_id=rt.family_id, absolute_expires=rt.absolute_expires_at)


@router.post("/logout", status_code=204)
def logout(body: LogoutIn, db: Session = Depends(get_db), _=Depends(rate_limit_api)):
    rt = db.scalar(select(RefreshToken).where(RefreshToken.token_hash == hash_token(body.refresh_token)))
    if rt is not None:
        revoke_family(db, rt.family_id)
    return Response(status_code=204)


@router.post("/change-password")
def change_password(body: ChangePasswordIn, request: Request, p: Principal = Depends(require_any), db: Session = Depends(get_db),
                    s: Settings = Depends(get_settings), sec: Security = Depends(get_security),
                    clock: Callable[[], float] = Depends(get_clock)):
    now = clock()
    user = db.get(User, p.user.initials)
    if not sec.verify_password(user.password_hash, body.current_password):
        audit(db, now, request, "change_bad_current", user.initials, p.device_id)
        raise fail(403, "bad_current_password", "The current password is not correct.")
    problem = password_problem(body.new_password, body.current_password, user.initials)
    if problem:
        raise fail(422, "weak_password", problem)
    user.password_hash = sec.hash_password(body.new_password)
    user.must_change, user.temp_expires_at, user.password_changed_at = False, None, now
    user.failed_count, user.locked_until = 0, None
    db.execute(update(RefreshToken).where(RefreshToken.initials == user.initials).values(status="revoked"))   # every other laptop signs out
    db.commit()
    audit(db, now, request, "password_changed", user.initials, p.device_id)
    return issue_session(db, sec, s, user, p.device_id, "full", now)
