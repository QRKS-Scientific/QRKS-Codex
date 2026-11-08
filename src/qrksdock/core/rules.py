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


def display_name(person: dict[str, str]) -> str:
    """The one place a lead's name is assembled for display: 'Lars E. Medice, RCh.' (credential only if they hold one)."""
    return f"{person['name']}, {person['credential']}" if person.get("credential") else person["name"]


def roster() -> list[dict[str, str]]:
    """Every lead, each with a ready-made `display_name`. Use that field in every screen, log and report."""
    out = []
    for person in load()["roster"]:
        entry = dict(person)
        entry["display_name"] = display_name(person)
        out.append(entry)
    return out


def display_name_of(initials: str) -> str:
    """Display name for initials; falls back to the initials themselves if the lead is not on the roster."""
    for person in roster():
        if person["initials"] == initials:
            return person["display_name"]
    return initials


def role_of(initials: str) -> str:
    for p in roster():
        if p["initials"] == initials:
            return p["role"]
    return ""


def docking_defaults() -> dict[str, Any]:
    return load()["docking"]


def peptide_rules() -> dict[str, Any]:
    return load()["peptide"]
