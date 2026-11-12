"""Run registry and activity events.

Data rule: this API never receives ligand names, SMILES, sequences, structures or scores. Event fields are
filtered through an allowlist (see schemas.EVENT_FIELDS). The chemistry travels through Google Drive only.
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Callable
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..config import Settings
from ..deps import Principal, fail, get_clock, get_db, get_settings, require_full
from ..models import Event, Run
from ..schemas import CODE_RE, EVENT_FIELDS, EventsIn, RunIn

router = APIRouter(prefix="/v1/runs", tags=["runs"])
STAGES = (("run_completed", "docked"), ("ligands_prepared", "ligands ready"), ("receptor_prepared", "receptor ready"))


def run_json(run: Run) -> dict:
    return {"code": run.code, "client_code": run.client_code, "package": run.package, "created_by": run.created_by,
            "created_at": run.created_at}


def summarize(run: Run, events: list[Event]) -> dict:
    """The dashboard row, derived from events so laptops never send a separate summary."""
    types = [e.type for e in events]
    stage = next((label for t, label in STAGES if t in types), "new")
    ligands = 0
    for e in reversed(events):
        if e.type in ("run_completed", "ligands_prepared"):
            ligands = int(json.loads(e.data).get("ligands", 0))
            break
    last = max(events, key=lambda e: e.received_at, default=None)
    return {**run_json(run), "stage": stage, "ligands": ligands, "reports": types.count("report_generated"),
            "last_actor": last.actor if last else run.created_by, "last_event_at": last.received_at if last else run.created_at}


@router.post("")
def create_or_register(body: RunIn, p: Principal = Depends(require_full), db: Session = Depends(get_db),
                       s: Settings = Depends(get_settings), clock: Callable[[], float] = Depends(get_clock)):
    """Allocate the next QDOCK code, or register one that already exists on a laptop. Safe to retry."""
    now = clock()
    if body.request_id:
        again = db.scalar(select(Run).where(Run.request_id == body.request_id))
        if again is not None:
            return run_json(again)
    if body.code:
        existing = db.get(Run, body.code)
        if existing is not None:
            if existing.client_code != body.client_code:
                raise fail(409, "code_conflict", f"{body.code} already belongs to {existing.client_code}.")
            return run_json(existing)
        m = CODE_RE.match(body.code)
        run = Run(code=body.code, client_code=body.client_code, date=m.group(1), serial=int(m.group(2)), package=body.package,
                  created_by=p.user.initials, created_at=now, request_id=body.request_id)
        db.add(run)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            raise fail(409, "code_conflict", "That QDOCK code is already taken.")
        return run_json(run)

    date = datetime.fromtimestamp(now, ZoneInfo(s.timezone)).strftime("%y%m%d")
    for _ in range(8):                                                     # the unique (date, serial) key settles races
        last = db.scalar(select(func.max(Run.serial)).where(Run.date == date)) or 0
        if last >= 999:
            raise fail(409, "serial_exhausted", "No more QDOCK codes are available today.")
        run = Run(code=f"QDOCK-{date}-{last + 1:03d}", client_code=body.client_code, date=date, serial=last + 1,
                  package=body.package, created_by=p.user.initials, created_at=now, request_id=body.request_id)
        db.add(run)
        try:
            db.commit()
            return run_json(run)
        except IntegrityError:
            db.rollback()
    raise fail(503, "busy", "Could not allocate a code. Try again.")


@router.get("")
def list_runs(client: str | None = None, p: Principal = Depends(require_full), db: Session = Depends(get_db)):
    q = select(Run).order_by(Run.code.desc()).limit(200)
    if client:
        q = q.where(Run.client_code == client.upper())
    out = []
    for run in db.scalars(q).all():
        events = db.scalars(select(Event).where(Event.run_code == run.code)).all()
        out.append(summarize(run, list(events)))
    return {"runs": out}


@router.post("/{code}/events")
def upload_events(code: str, body: EventsIn, p: Principal = Depends(require_full), db: Session = Depends(get_db),
                  clock: Callable[[], float] = Depends(get_clock)):
    if db.get(Run, code) is None:
        raise fail(404, "unknown_run", f"{code} is not registered.")
    now, accepted, duplicates, dropped = clock(), 0, 0, 0
    ids = {e.id for e in body.events}
    known = set(db.scalars(select(Event.id).where(Event.id.in_(ids))).all()) if ids else set()
    for e in body.events:
        if e.id in known:
            duplicates += 1
            continue
        try:
            datetime.fromisoformat(e.utc.replace("Z", "+00:00"))
        except ValueError:
            raise fail(422, "bad_time", f"Event {e.id} has an invalid time.")
        allowed = EVENT_FIELDS[e.type]
        clean = {k: v for k, v in e.data.items() if k in allowed and isinstance(v, (str, int, float, bool)) and len(str(v)) <= 120}
        dropped += len(e.data) - len(clean)
        db.add(Event(id=e.id, run_code=code, actor=p.user.initials, type=e.type, utc=e.utc, data=json.dumps(clean), received_at=now))
        known.add(e.id)
        accepted += 1
    db.commit()
    return {"accepted": accepted, "duplicates": duplicates, "fields_dropped": dropped}


@router.get("/{code}/events")
def get_events(code: str, p: Principal = Depends(require_full), db: Session = Depends(get_db)):
    if db.get(Run, code) is None:
        raise fail(404, "unknown_run", f"{code} is not registered.")
    rows = db.scalars(select(Event).where(Event.run_code == code).order_by(Event.utc)).all()
    return {"events": [{"id": e.id, "type": e.type, "actor": e.actor, "utc": e.utc, "data": json.loads(e.data)} for e in rows]}
