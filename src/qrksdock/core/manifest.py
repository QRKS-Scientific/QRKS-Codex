"""Run manifest: everything needed to reproduce a result, plus a tamper-evident hash.

Every docking run writes manifest.json containing software versions, parameters, seeds,
and SHA-256 hashes of the input and output files. The manifest's own hash (its "Run ID")
is printed in the report, so anyone can later check that a report matches its data.
"""
from __future__ import annotations

import hashlib
import json
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from qrksdock import __version__
from qrksdock.core import rules


def sha256_file(path: Path | str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _pkg_version(dist: str, module: str | None = None) -> str:
    try:
        from importlib.metadata import version
        return version(dist)
    except Exception:                                              # noqa: BLE001
        try:
            mod = __import__(module or dist)
            return str(getattr(mod, "__version__", "unknown"))
        except Exception:                                          # noqa: BLE001
            return "unavailable"


def environment(vina_version: str | None = None) -> dict[str, str]:
    return {
        "qrksdock": __version__,
        "rules": rules.load()["rules_version"],
        "autodock_vina": vina_version or "unknown",
        "rdkit": _pkg_version("rdkit", "rdkit"),
        "meeko": _pkg_version("meeko"),
        "molscrub": _pkg_version("molscrub"),
        "pdb2pqr": _pkg_version("pdb2pqr"),
        "propka": _pkg_version("propka"),
        "python": platform.python_version(),
        "platform": f"{platform.system()} {platform.machine()}",
        "frozen_app": str(bool(getattr(sys, "frozen", False))),
    }


def canonical_hash(payload: dict[str, Any]) -> str:
    body = {k: v for k, v in payload.items() if k != "run_id"}
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def hashes(files: dict[str, Path]) -> dict[str, str]:
    return {label: sha256_file(p) for label, p in files.items() if p and Path(p).exists()}


def write_manifest(path: Path, payload: dict[str, Any]) -> str:
    payload = dict(payload)
    payload["generated_utc"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    payload["run_id"] = canonical_hash(payload)[:16].upper()
    Path(path).write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    return payload["run_id"]
