from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from qrksdock import paths
from qrksdock.net.client import ApiClient
from qrksdock.net.outbox import Outbox
from qrksdock.net.session import SessionManager
from qrksdock.net.store import SecretStore, default_store
from qrksdock.net.sync import SyncService

def get_supabase_config() -> tuple[str, str]:
    """Reads the Supabase URL and Key from server.json"""
    config_path = paths.user_data_dir() / "server.json"
    try:
        with open(config_path, "r") as f:
            data = json.load(f)
            return data.get("supabase_url", ""), data.get("supabase_key", "")
    except (FileNotFoundError, json.JSONDecodeError):
        return "", ""

@dataclass
class NetServices:
    api: ApiClient
    session: SessionManager
    outbox: Outbox
    sync: SyncService

    @classmethod
    def create(cls, *, store: SecretStore | None = None,
               outbox_path: Path | None = None, clock: Callable[[], float] = time.time) -> "NetServices | None":
        
        url, key = get_supabase_config()
        if not url or not key:
            return None
            
        api = ApiClient(url, key)
        session = SessionManager(api, store or default_store(), clock)
        outbox = Outbox(outbox_path or paths.user_data_dir() / "outbox.sqlite")
        return cls(api, session, outbox, SyncService(api, session, outbox))

    def create_run(self, client_code: str, package: str = "") -> str:
        return self.sync.create_run(client_code, package)