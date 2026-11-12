"""Server-side administration. There are deliberately no admin HTTP endpoints.

    python -m app.admin init --roster roster.json     create the six lead accounts (prints temporary passwords once)
    python -m app.admin reset JER                      new temporary password; signs that lead out everywhere
    python -m app.admin unlock JER | disable JER | enable JER
    python -m app.admin devices JER | revoke-devices JER
    python -m app.admin list | audit [--limit 30]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from .config import Settings
from .db import make_engine, make_sessionmaker
from .models import AuthEvent, Base, Device, RefreshToken, User
from .security import Security, temp_password


def create_users(db: Session, sec: Security, s: Settings, roster: list[dict], now: float) -> dict[str, str]:
    """Create any lead who does not exist yet. Returns {initials: temporary password} for the new ones only."""
    issued: dict[str, str] = {}
    for p in roster:
        ini = p["initials"].upper()
        if db.get(User, ini) is None:
            pw = temp_password()
            db.add(User(initials=ini, display_name=p["display_name"], role=p["role"], password_hash=sec.hash_password(pw),
                        must_change=True, temp_expires_at=now + s.temp_password_days * 86400, created_at=now))
            issued[ini] = pw
    db.commit()
    return issued


def reset_user(db: Session, sec: Security, s: Settings, initials: str, now: float) -> str:
    user = db.get(User, initials.upper())
    if user is None:
        raise KeyError(initials)
    pw = temp_password()
    user.password_hash, user.must_change = sec.hash_password(pw), True
    user.temp_expires_at, user.failed_count, user.locked_until = now + s.temp_password_days * 86400, 0, None
    db.execute(update(RefreshToken).where(RefreshToken.initials == user.initials).values(status="revoked"))
    db.commit()
    return pw


def set_flag(db: Session, initials: str, **fields) -> None:
    user = db.get(User, initials.upper())
    if user is None:
        raise KeyError(initials)
    for k, v in fields.items():
        setattr(user, k, v)
    if fields.get("disabled"):
        db.execute(update(RefreshToken).where(RefreshToken.initials == user.initials).values(status="revoked"))
    db.commit()


def revoke_devices(db: Session, initials: str) -> int:
    ini = initials.upper()
    devices = db.scalars(select(Device).where(Device.initials == ini)).all()
    for d in devices:
        d.revoked = True
    db.execute(update(RefreshToken).where(RefreshToken.initials == ini).values(status="revoked"))
    db.commit()
    return len(devices)


def _fmt(ts: float | None) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%d %H:%M UTC") if ts else "-"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m app.admin")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("init"); p.add_argument("--roster", required=True)
    for name in ("reset", "unlock", "disable", "enable", "devices", "revoke-devices"):
        sub.add_parser(name).add_argument("initials")
    sub.add_parser("list")
    a = sub.add_parser("audit"); a.add_argument("--limit", type=int, default=30)
    args = ap.parse_args(argv)

    s = Settings()
    engine = make_engine(s.database_url)
    Base.metadata.create_all(engine)
    sec, now = Security(s), time.time()
    with make_sessionmaker(engine)() as db:
        try:
            if args.cmd == "init":
                issued = create_users(db, sec, s, json.loads(Path(args.roster).read_text(encoding="utf-8")), now)
                if not issued:
                    print("All accounts already exist. Use `reset INITIALS` to issue a new temporary password.")
                for ini, pw in issued.items():
                    print(f"{ini:<4} {pw}")
                if issued:
                    print(f"\nTemporary passwords are shown ONCE. Each is valid for {s.temp_password_days} days and ends at first password change.")
            elif args.cmd == "reset":
                print(f"{args.initials.upper()}  {reset_user(db, sec, s, args.initials, now)}\n(valid {s.temp_password_days} days; the lead is signed out everywhere)")
            elif args.cmd == "unlock":
                set_flag(db, args.initials, failed_count=0, locked_until=None); print("unlocked")
            elif args.cmd in ("disable", "enable"):
                set_flag(db, args.initials, disabled=(args.cmd == "disable")); print(args.cmd + "d")
            elif args.cmd == "devices":
                for d in db.scalars(select(Device).where(Device.initials == args.initials.upper())):
                    print(f"{d.device_id[:12]}  {d.name or '-':<24} last seen {_fmt(d.last_seen)}  {'REVOKED' if d.revoked else 'active'}")
            elif args.cmd == "revoke-devices":
                print(f"revoked {revoke_devices(db, args.initials)} device(s)")
            elif args.cmd == "list":
                for u in db.scalars(select(User).order_by(User.initials)):
                    state = "disabled" if u.disabled else ("temporary password" if u.must_change else "active")
                    print(f"{u.initials:<4} {u.display_name:<28} {u.role:<22} {state}")
            elif args.cmd == "audit":
                for e in db.scalars(select(AuthEvent).order_by(AuthEvent.utc.desc()).limit(args.limit)):
                    print(f"{_fmt(e.utc)}  {e.initials or '-':<4} {e.outcome:<18} {e.ip:<16} {e.detail}")
        except KeyError as exc:
            print(f"No such account: {exc}", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
