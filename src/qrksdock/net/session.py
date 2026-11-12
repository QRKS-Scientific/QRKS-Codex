"""The signed-in session using Supabase Auth.
  * Supabase SDK automatically handles token refresh and storage.
  * With no internet, the local outbox takes over.
"""
from __future__ import annotations

import platform
import time
import uuid
from typing import Callable

from qrksdock.core.accounts import AuthResult
from qrksdock.net.client import ApiClient
from qrksdock.net.config import GRACE_DAYS
from qrksdock.net.errors import ApiError, Offline
from qrksdock.net.store import SecretStore

OFFLINE_MESSAGE = "Cannot reach the QRKS server. Check your internet connection."

class SessionManager:
    def __init__(self, api: ApiClient, store: SecretStore, clock: Callable[[], float] = time.time, grace_days: int = GRACE_DAYS):
        self.api = api
        self.store = store
        self.clock = clock
        self.grace = grace_days * 86400
        
        self.initials = ""
        self.display_name = ""
        self.offline = False
        self.session_lost = False

    @property
    def device_id(self) -> str:
        did = self.store.get("device_id")
        if not did:
            did = "dev-" + uuid.uuid4().hex
            self.store.set("device_id", did)
        return did

    @property
    def device_name(self) -> str:
        return f"{platform.system()} {platform.machine()}"[:80]

    def _sync_user_state(self):
        """Pulls user metadata from the active Supabase session."""
        res = self.api.me()
        if res and res.user:
            # Assuming initials are stored in Supabase user metadata
            self.initials = res.user.user_metadata.get("initials", res.user.email[:2].upper()) # <-- RIGHT HERE
            self.display_name = res.user.user_metadata.get("display_name", self.initials)
            self.offline = False
        else:
            self.initials = ""

    def login(self, email: str, password: str) -> AuthResult:
        self.session_lost = False
        try:
            self.api.login(email, password)
            self._sync_user_state()
            return AuthResult(True, must_change=False)
        except Offline:
            return AuthResult(False, message=OFFLINE_MESSAGE)
        except ApiError as exc:
            return AuthResult(False, message=exc.message)

    def change_password(self, current: str, new: str) -> None:
        try:
            self.api.change_password(new)
        except Offline:
            raise ValueError(OFFLINE_MESSAGE)
        except ApiError as exc:
            raise ValueError(exc.message)

    def resume(self) -> str | None:
        """Silent sign-in checking Supabase's active session."""
        try:
            self._sync_user_state()
            if self.initials:
                return self.initials
            return None
        except Offline:
            self.offline = True
            # Allow UI to open in offline mode if previously logged in
            return self.initials if self.initials else None
        except Exception:
            return None

    def sign_out(self) -> None:
        try:
            self.api.logout()
        except Exception:
            pass
        self.initials = ""
        self.display_name = ""
        self.offline = False