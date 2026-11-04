"""Locate bundled resources and per-user folders, in development and in the frozen app."""
from __future__ import annotations

import os
import sys
from pathlib import Path


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def base_dir() -> Path:
    """Folder that holds assets/ and bin/ (project root in dev, bundle folder when frozen)."""
    if is_frozen():
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parents[2]


def asset(*parts: str) -> Path:
    return base_dir().joinpath("assets", *parts)


def bin_dir() -> Path:
    return base_dir() / "bin"


def data_file(name: str) -> Path:
    if is_frozen():
        return base_dir() / "qrksdock_data" / name
    return Path(__file__).resolve().parent / "data" / name


def user_data_dir() -> Path:
    if sys.platform == "win32":
        root = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    elif sys.platform == "darwin":
        root = Path.home() / "Library" / "Application Support"
    else:
        root = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    p = root / "QRKSDock"
    p.mkdir(parents=True, exist_ok=True)
    return p
