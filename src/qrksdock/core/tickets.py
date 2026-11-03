"""Ticket folders, event log and permission gates.

A ticket is a folder (normally inside the shared Google Drive client directory):

    [QDOCK-YYMMDD-XXX]/
        ticket.json     written once when the ticket is created, never edited
        events/         append-only: one small JSON file per event
        input/  work/  results/  reports/

Status never lives in a file that two people edit. Every change (payment verified,
QA passed, run completed...) is its own event file, so Google Drive can sync
changes from several laptops without conflicts. Flags are derived by replaying events.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from qrksdock import __version__
from qrksdock.core import rules

SUBFOLDERS = ("input", "work", "results", "reports", "events")
_ID_RE = re.compile(r"^(?P<prefix>[A-Z]+)-(?P<date>\d{6})-(?P<serial>\d{3})$")


class PermissionDenied(Exception):
    pass


class TicketError(Exception):
    pass


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _atomic_write(path: Path, text: str) -> None:
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def folder_name(ticket_id: str) -> str:
    return f"[{ticket_id}]" if rules.load()["ticket"]["folder_brackets"] else ticket_id


def parse_ticket_id(name: str) -> dict[str, str] | None:
    m = _ID_RE.match(name.strip().strip("[]"))
    return m.groupdict() if m else None


def next_ticket_id(root: Path, test: bool = False, today: datetime | None = None) -> str:
    cfg = rules.load()["ticket"]
    prefix = cfg["test_prefix"] if test else cfg["prefix"]
    date = (today or datetime.now()).strftime("%y%m%d")
    highest = 0
    if root.exists():
        for child in root.iterdir():
            parsed = parse_ticket_id(child.name)
            if parsed and parsed["prefix"] == prefix and parsed["date"] == date:
                highest = max(highest, int(parsed["serial"]))
    return f"{prefix}-{date}-{highest + 1:03d}"


@dataclass
class Ticket:
    path: Path
    meta: dict[str, Any] = field(default_factory=dict)

    # ---- creation / opening -------------------------------------------------
    @classmethod
    def create(cls, root: Path, tier: str, actor: str, client_ref: str = "",
               test: bool = False, ticket_id: str | None = None) -> "Ticket":
        if tier not in rules.tiers():
            raise TicketError(f"Unknown tier '{tier}'. Valid tiers: {', '.join(rules.tiers())}")
        if not test and not rules.can(actor, "create_ticket"):
            raise PermissionDenied(f"{actor} ({rules.role_of(actor) or 'unknown role'}) cannot create tickets.")
        root.mkdir(parents=True, exist_ok=True)
        tid = ticket_id or next_ticket_id(root, test=test)
        path = root / folder_name(tid)
        if path.exists() and (path / "ticket.json").exists():
            raise TicketError(f"Ticket {tid} already exists at {path}")
        for sub in SUBFOLDERS:
            (path / sub).mkdir(parents=True, exist_ok=True)
        meta = {
            "schema": 1, "ticket_id": tid, "service": "QRKSDock", "tier": tier,
            "client_ref": client_ref, "test": bool(test),
            "created_utc": _utc_now().isoformat(timespec="seconds"),
            "created_by": actor, "app_version": __version__,
        }
        _atomic_write(path / "ticket.json", json.dumps(meta, indent=2))
        t = cls(path, meta)
        t.add_event(actor, "ticket_created", {"tier": tier, "test": bool(test)})
        return t

    @classmethod
    def open(cls, path: Path) -> "Ticket":
        meta_file = Path(path) / "ticket.json"
        if not meta_file.exists():
            raise TicketError(f"No ticket.json in {path}. Choose a QRKSDock ticket folder.")
        t = cls(Path(path), json.loads(meta_file.read_text(encoding="utf-8")))
        for sub in SUBFOLDERS:                      # Drive may not have synced empty folders
            (t.path / sub).mkdir(exist_ok=True)
        return t

    # ---- basic properties -----------------------------------------------------
    @property
    def id(self) -> str:
        return self.meta["ticket_id"]

    @property
    def tier(self) -> str:
        return self.meta["tier"]

    @property
    def is_test(self) -> bool:
        return bool(self.meta.get("test"))

    def sub(self, name: str) -> Path:
        p = self.path / name
        p.mkdir(parents=True, exist_ok=True)
        return p

    # ---- events -------------------------------------------------------------------
    def add_event(self, actor: str, etype: str, data: dict[str, Any] | None = None) -> Path:
        now = _utc_now()
        payload = {"type": etype, "actor": actor, "utc": now.isoformat(timespec="microseconds"),
                   "data": data or {}, "app_version": __version__}
        fname = f"{now:%Y%m%dT%H%M%S%f}Z__{actor}__{etype}.json"
        path = self.sub("events") / fname
        _atomic_write(path, json.dumps(payload, indent=2))
        return path

    def events(self) -> list[dict[str, Any]]:
        out = []
        for f in sorted(self.sub("events").glob("*.json")):
            try:
                out.append(json.loads(f.read_text(encoding="utf-8")))
            except (OSError, json.JSONDecodeError):
                continue                             # a half-synced file; ignore it
        return sorted(out, key=lambda e: e.get("utc", ""))

    # ---- flags ------------------------------------------------------------------------
    def flags(self) -> dict[str, bool]:
        state = {name: False for name in rules.flag_defs()}
        for e in self.events():
            if e["type"] == "flag_set" and e["data"].get("flag") in state:
                state[e["data"]["flag"]] = bool(e["data"].get("value"))
        return state

    def set_flag(self, actor: str, flag: str, value: bool = True) -> None:
        if flag not in rules.flag_defs():
            raise TicketError(f"Unknown flag '{flag}'")
        if not self.is_test and not rules.can_set_flag(actor, flag):
            who = ", ".join(rules.flag_defs()[flag]["who"])
            raise PermissionDenied(f"Only {who} can change '{rules.flag_defs()[flag]['label']}'. "
                                   f"You are signed in as {actor} ({rules.role_of(actor)}).")
        self.add_event(actor, "flag_set", {"flag": flag, "value": bool(value)})

    # ---- gates --------------------------------------------------------------------------
    def check_can_run(self, actor: str) -> None:
        """Raise PermissionDenied unless this operator may run docking on this ticket now."""
        if self.is_test:
            return
        if not rules.can(actor, "run_docking"):
            raise PermissionDenied(f"{actor} ({rules.role_of(actor)}) cannot run docking. "
                                   "Docking is executed by the Technical Lead.")
        if not self.flags()["activated_paid"]:
            raise PermissionDenied("This ticket is not ACTIVATED & PAID yet. "
                                   "Ask the Finance Lead (JCG) to verify payment first.")

    def check_can_report(self, actor: str) -> None:
        if not self.is_test and not rules.can(actor, "generate_report"):
            raise PermissionDenied(f"{actor} ({rules.role_of(actor)}) cannot generate reports.")

    def report_state(self) -> dict[str, Any]:
        """What the report may show: watermark and Integrity Seal are decided here, nowhere else."""
        f = self.flags()
        seal = f["qa_passed"] and f["report_signed"] and not self.is_test
        watermark = self.is_test or not f["balance_cleared"]
        return {"seal": seal, "watermark": watermark, "test": self.is_test, "flags": f}

    def check_limits(self, n_small: int, n_peptides: int) -> list[str]:
        lim = rules.tier_limits(self.tier)
        issues = []
        if n_small > lim["small_molecules"]:
            issues.append(f"{n_small} small molecules exceeds the {self.tier} limit of {lim['small_molecules']}.")
        if n_peptides > lim["peptides"]:
            issues.append(f"{n_peptides} peptides exceeds the {self.tier} limit of {lim['peptides']}.")
        return issues
