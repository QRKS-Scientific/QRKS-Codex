"""A local queue of activity events, uploaded when the laptop is online.

Event data is filtered here, before it is even queued, by the same allowlist the server enforces:
ligand names, SMILES, sequences, structures and scores never enter the queue.
"""
from __future__ import annotations

import json
import sqlite3
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

ALLOWED_FIELDS: dict[str, set[str]] = {
    "run_created": {"package"},
    "receptor_prepared": {"method", "ph", "box"},
    "ligands_prepared": {"ligands", "states"},
    "validation_completed": {"rmsd_top", "passed"},
    "run_completed": {"run_id", "ligands", "vina"},
    "ligand_renamed": set(),
    "report_generated": {"final", "file"},
}


def safe_data(kind: str, data: dict) -> dict:
    allowed = ALLOWED_FIELDS.get(kind, set())
    return {k: v for k, v in (data or {}).items() if k in allowed and isinstance(v, (str, int, float, bool))}


@dataclass
class Pending:
    id: str
    run_code: str
    client_code: str
    kind: str
    utc: str
    data: dict


class Outbox:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as c:
            c.execute("CREATE TABLE IF NOT EXISTS events (id TEXT PRIMARY KEY, run_code TEXT, client_code TEXT, kind TEXT, utc TEXT,"
                      " data TEXT, state INTEGER DEFAULT 0, created REAL)")          # state: 0 waiting, 1 sent, 2 rejected

    def _conn(self) -> sqlite3.Connection:
        c = sqlite3.connect(self.path, timeout=5)
        c.execute("PRAGMA journal_mode=WAL")
        return c

    def enqueue(self, run_code: str, client_code: str, kind: str, data: dict | None, utc: str, event_id: str | None = None) -> str | None:
        if kind not in ALLOWED_FIELDS:
            return None                                       # activity that is not shared (for example local-only notes)
        eid = event_id or uuid.uuid4().hex
        with self._conn() as c:
            c.execute("INSERT OR IGNORE INTO events (id, run_code, client_code, kind, utc, data, state, created) VALUES (?,?,?,?,?,?,0,?)",
                      (eid, run_code, client_code, kind, utc, json.dumps(safe_data(kind, data or {})), time.time()))
        return eid

    def pending(self, limit: int = 200) -> list[Pending]:
        with self._conn() as c:
            rows = c.execute("SELECT id, run_code, client_code, kind, utc, data FROM events WHERE state=0 ORDER BY created LIMIT ?", (limit,)).fetchall()
        return [Pending(r[0], r[1], r[2], r[3], r[4], json.loads(r[5])) for r in rows]

    def mark(self, ids: list[str], state: int) -> None:
        with self._conn() as c:
            c.executemany("UPDATE events SET state=? WHERE id=?", [(state, i) for i in ids])

    def count(self) -> int:
        with self._conn() as c:
            return c.execute("SELECT COUNT(*) FROM events WHERE state=0").fetchone()[0]
