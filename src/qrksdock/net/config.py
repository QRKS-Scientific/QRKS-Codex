"""Which server to talk to. No address configured means local accounts (development mode)."""
from __future__ import annotations

import json
import os

from qrksdock import paths

GRACE_DAYS = 7                      # how long a cached sign-in keeps working with no internet


def server_url() -> str | None:
    env = os.environ.get("QRKS_SERVER_URL", "").strip()
    if env:
        return env
    try:
        url = json.loads(paths.data_file("server.json").read_text(encoding="utf-8")).get("url", "").strip()
    except (OSError, json.JSONDecodeError):
        url = ""
    return url or None
