"""The signed-in session on this laptop using Supabase Auth.
  * The session JSON lives in the OS keychain.
  * Signing out revokes the session on the server and wipes the keychain entry.
"""
from __future__ import annotations

import json
import time
from typing import Callable

from qrksdock.core import rules
from qrksdock.core.accounts import AuthResult
from qrksdock.net.client import ApiClient
from qrksdock.net.config import GRACE_DAYS
from qrksdock.net.store import SecretStore

OFFLINE_MESSAGE = "Cannot reach the QRKS server. Check your internet connection."


def _initials_for_email(email: str) -> str:
    clean = email.strip().lower()
    for person in rules.roster():
        roster_email = (person.get("email") or f"{person['initials'].lower()}@qrks.com").lower()
        if roster_email == clean:
            return person["initials"]
    return clean.split("@")[0].upper()


class SessionManager:
    def __init__(self, api: ApiClient, store: SecretStore, clock: Callable[[], float] = time.time, grace_days: int = GRACE_DAYS):
        self.api = api
        self.store = store
        self.clock = clock
        self.grace = grace_days * 86400
        self.initials = ""
        self.offline = False
        self.session_lost = False

        self._restore_supabase_session()

    def _restore_supabase_session(self) -> None:
        raw = self.store.get("session")
        if raw:
            try:
                saved = json.loads(raw)
                self.api.sb.auth.set_session(saved["access_token"], saved["refresh_token"])
                self.initials = saved.get("initials", "")
            except Exception:
                self.store.delete("session")

    def _persist_session(self, session, initials: str) -> None:
        self.initials = initials
        self.store.set("session", json.dumps({
            "access_token": session.access_token,
            "refresh_token": session.refresh_token,
            "initials": initials,
            "last_verified": self.clock(),
        }))

    def _end(self) -> None:
        self.initials = ""
        self.store.delete("session")
        try:
            self.api.sb.auth.sign_out()
        except Exception:
            pass

    def access(self) -> str | None:
        """Ensure session is valid and return the access token."""
        try:
            session = self.api.sb.auth.get_session()
            return session.access_token if session else None
        except Exception:
            return None

    def login(self, email: str, password: str) -> AuthResult:
        self.session_lost = False
        clean_email = email.strip().lower()
        if "@" not in clean_email:
            return AuthResult(False, message="Enter a valid email address.")
        initials = _initials_for_email(clean_email)

        try:
            response = self.api.sb.auth.sign_in_with_password({"email": clean_email, "password": password})
            if response.session:
                self._persist_session(response.session, initials)
                return AuthResult(True, must_change=False)
            return AuthResult(False, message="Login failed.")
        except Exception as exc:
            error_msg = getattr(exc, "message", str(exc))
            if any(term in str(exc) for term in ("Failed to establish a new connection", "Network", "ConnectError", "Timeout")):
                return AuthResult(False, message=OFFLINE_MESSAGE)
            return AuthResult(False, message=error_msg)

    def change_password(self, email: str, current: str, new: str) -> None:
        if not self.access():
            raise ValueError("Sign in again first.")
        try:
            self.api.sb.auth.update_user({"password": new})
        except Exception as exc:
            raise ValueError(getattr(exc, "message", str(exc)))

    def resume(self) -> str | None:
        """Silent sign-in from the saved session."""
        if self.access():
            return self.initials
        return None

    def sign_out(self) -> None:
        self._end()
        self.offline = False