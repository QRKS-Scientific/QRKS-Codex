"""Runs: QDOCK codes, client codes and the run folder layout.

Every docking job is a *run*. A run is identified by two codes only:

    client code   QC-001                 (one per client)
    QDOCK code    QDOCK-260824-001       (QDOCK-YYMMDD-serial, unique per day)

and lives in a plain folder, ready to be synced to Google Drive:

    <runs folder>/QC-001/QDOCK-260824-001/
        run.json        written once when the run is created
        input/          copies of the supplied receptor, reference ligand and ligand lists
        work/           prepared structures and Vina's per-ligand output
        results/        results.csv, poses.csv, poses/*.sdf, vina_output.log, manifest.json
        reports/        PDF reports
        logs/           activity.jsonl: who did what, and when

There are no statuses, flags or locks. Nothing here can block a run.
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

SUBFOLDERS = ("input", "work", "results", "reports", "logs")
CLIENT_RE = re.compile(r"^QC-(\d{3,6})$")
QDOCK_RE = re.compile(r"^QDOCK-(\d{6})-(\d{3})$")


class RunError(Exception):
    pass


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def normalize_client_code(raw: str) -> str:
    """'qc-7' and ' QC-007 ' both become 'QC-007'. Raises RunError for anything else."""
    text = raw.strip().upper().strip("[]")
    m = re.match(r"^QC-(\d{1,6})$", text)
    if not m:
        raise RunError(f"'{raw}' is not a client code. Use the form QC-001.")
    return f"QC-{int(m.group(1)):03d}" if len(m.group(1)) < 3 else f"QC-{m.group(1)}"


def parse_qdock_code(name: str) -> dict[str, str] | None:
    m = QDOCK_RE.match(name.strip().strip("[]"))
    return {"date": m.group(1), "serial": m.group(2)} if m else None


def _atomic_write(path: Path, text: str) -> None:
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def next_qdock_code(root: Path, today: datetime | None = None) -> str:
    """The next free QDOCK-YYMMDD-NNN across *all* clients under the runs folder."""
    date = (today or datetime.now()).strftime("%y%m%d")
    highest = 0
    if root.exists():
        for client in root.iterdir():
            if not client.is_dir():
                continue
            for child in list(client.iterdir()) + [client]:
                parsed = parse_qdock_code(child.name)
                if parsed and parsed["date"] == date:
                    highest = max(highest, int(parsed["serial"]))
    return f"QDOCK-{date}-{highest + 1:03d}"


@dataclass
class Run:
    path: Path
    meta: dict[str, Any] = field(default_factory=dict)

    # ---- create / open ---------------------------------------------------------------
    @classmethod
    def create(cls, root: Path, client_code: str, actor: str, package: str | None = None,
               notes: str = "", qdock_code: str | None = None) -> "Run":
        client = normalize_client_code(client_code)
        if package and package not in rules.tiers():
            raise RunError(f"Unknown package '{package}'. Valid packages: {', '.join(rules.tiers())}")
        code = qdock_code or next_qdock_code(root)
        if not QDOCK_RE.match(code):
            raise RunError(f"'{code}' is not a QDOCK code. Use the form QDOCK-YYMMDD-001.")
        path = root / client / code
        if (path / "run.json").exists():
            raise RunError(f"{code} already exists for {client}.")
        for sub in SUBFOLDERS:
            (path / sub).mkdir(parents=True, exist_ok=True)
        meta = {"schema": 2, "qdock_code": code, "client_code": client, "package": package or "",
                "notes": notes, "created_utc": _utc_now().isoformat(timespec="seconds"),
                "created_by": actor, "app_version": __version__}
        _atomic_write(path / "run.json", json.dumps(meta, indent=2))
        run = cls(path, meta)
        run.log(actor, "run_created", {"package": package or "none"})
        return run

    @classmethod
    def open(cls, path: Path, actor: str = "") -> "Run":
        """Open a run folder. A folder that was created by hand with a QDOCK code name inside
        a QC-xxx folder (for example by the Documentations Lead on Drive) is adopted."""
        path = Path(path)
        meta_file = path / "run.json"
        if not meta_file.exists():
            parsed = parse_qdock_code(path.name)
            if not parsed or not CLIENT_RE.match(path.parent.name.strip("[]").upper()):
                raise RunError(f"{path.name} is not a QRKSDock run folder. Choose a folder named like "
                               "QDOCK-260824-001 inside a client folder named like QC-001, or create a new run.")
            return cls.create(path.parent.parent, path.parent.name, actor or "?", qdock_code=path.name.strip("[]"))
        run = cls(path, json.loads(meta_file.read_text(encoding="utf-8")))
        for sub in SUBFOLDERS:                       # Drive does not always sync empty folders
            (path / sub).mkdir(exist_ok=True)
        return run

    # ---- properties --------------------------------------------------------------------------
    @property
    def code(self) -> str:
        return self.meta["qdock_code"]

    @property
    def client(self) -> str:
        return self.meta["client_code"]

    @property
    def package(self) -> str:
        return self.meta.get("package", "")

    @property
    def label(self) -> str:
        return f"{self.client}  |  {self.code}"

    def sub(self, name: str) -> Path:
        p = self.path / name
        p.mkdir(parents=True, exist_ok=True)
        return p

    # ---- activity log (a record of what happened, never a gate) -----------------------------
    def log(self, actor: str, kind: str, data: dict[str, Any] | None = None) -> None:
        entry = {"utc": _utc_now().isoformat(timespec="seconds"), "actor": actor, "type": kind,
                 "data": data or {}, "app_version": __version__}
        with open(self.sub("logs") / "activity.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")

    def activity(self, limit: int = 30) -> list[dict[str, Any]]:
        f = self.sub("logs") / "activity.jsonl"
        if not f.exists():
            return []
        out = []
        for line in f.read_text(encoding="utf-8").splitlines():
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue                             # a half-synced line
        return out[-limit:]

    # ---- package limits (only when a package was chosen) --------------------------------------
    def check_limits(self, n_small: int, n_peptides: int) -> list[str]:
        if not self.package:
            return []
        lim = rules.tier_limits(self.package)
        issues = []
        if n_small > lim["small_molecules"]:
            issues.append(f"{n_small} small molecules exceeds the {self.package} limit of {lim['small_molecules']}.")
        if n_peptides > lim["peptides"]:
            issues.append(f"{n_peptides} peptides exceeds the {self.package} limit of {lim['peptides']}.")
        return issues


def list_runs(root: Path) -> list[dict[str, Any]]:
    """Every run under the runs folder, newest first, with a one-line progress summary."""
    rows: list[dict[str, Any]] = []
    if not root.exists():
        return rows
    for client in sorted(root.iterdir()):
        if not client.is_dir() or not CLIENT_RE.match(client.name.strip("[]").upper()):
            continue
        for run_dir in client.iterdir():
            meta_file = run_dir / "run.json"
            if not run_dir.is_dir() or not meta_file.exists():
                continue
            try:
                meta = json.loads(meta_file.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            state: dict[str, Any] = {}
            sf = run_dir / "work" / "state.json"
            if sf.exists():
                try:
                    state = json.loads(sf.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    pass
            results = state.get("results", [])
            best = min((r["best_affinity"] for r in results), default=None)
            stage = ("docked" if results else "ligands ready" if state.get("prepared")
                     else "receptor ready" if state.get("receptor") else "new")
            rows.append({"client": meta.get("client_code", client.name), "code": meta.get("qdock_code", run_dir.name),
                         "path": run_dir, "created": meta.get("created_utc", "")[:10], "by": meta.get("created_by", ""),
                         "package": meta.get("package", ""), "stage": stage,
                         "ligands": len({r["ligand"] for r in results}), "best": best,
                         "reports": len(list((run_dir / "reports").glob("*.pdf"))) if (run_dir / "reports").exists() else 0})
    rows.sort(key=lambda r: r["code"], reverse=True)
    return rows
