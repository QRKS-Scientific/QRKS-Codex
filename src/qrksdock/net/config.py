"""Which server to talk to. No address configured means local accounts (development mode)."""
from __future__ import annotations

import json
import os
from typing import Tuple

from qrksdock import paths

GRACE_DAYS = 7                      # how long a cached sign-in keeps working with no internet


def supabase_credentials() -> Tuple[str | None, str | None]:
    env_url = os.environ.get("SUPABASE_URL", "").strip()
    env_key = os.environ.get("SUPABASE_ANON_KEY", "").strip()
    if env_url and env_key:
        return env_url, env_key
    try:
        data = json.loads(paths.data_file("server.json").read_text(encoding="utf-8"))
        url = data.get("supabase_url", "").strip()
        key = data.get("supabase_anon_key", "").strip()
        return url or None, key or None
    except (OSError, json.JSONDecodeError):
        return None, None


def server_url() -> str | None:
    """Backward-compatible helper returning the configured Supabase URL."""
    url, _ = supabase_credentials()
    return url