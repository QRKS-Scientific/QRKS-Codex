"""Business rules (tiers, roster, permissions, docking defaults) loaded from rules.json."""
from __future__ import annotations

import json
from functools import lru_cache
from typing import Any

from qrksdock import paths


@lru_cache(maxsize=1)
def load() -> dict[str, Any]:
    return json.loads(paths.data_file("rules.json").read_text(encoding="utf-8"))


def tiers() -> list[str]:
    return list(load()["tiers"])


def tier_limits(tier: str) -> dict[str, Any]:
    return load()["tiers"][tier]


def roster() -> list[dict[str, str]]:
    return load()["roster"]


def role_of(initials: str) -> str:
    for p in roster():
        if p["initials"] == initials:
            return p["role"]
    return ""


def can(initials: str, action: str) -> bool:
    return initials in load()["permissions"].get(action, [])


def flag_defs() -> dict[str, dict[str, Any]]:
    return load()["flags"]


def can_set_flag(initials: str, flag: str) -> bool:
    return initials in flag_defs()[flag]["who"]


def docking_defaults() -> dict[str, Any]:
    return load()["docking"]


def peptide_rules() -> dict[str, Any]:
    return load()["peptide"]
