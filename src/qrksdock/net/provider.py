"""The sign-in screen talks to an AuthProvider. Two exist:
    AccountStore (core/accounts.py)  local accounts file: development and the offline fallback of v0.4
    RemoteAuthProvider (here)        the QRKS server
"""
from __future__ import annotations

from qrksdock.core import rules
from qrksdock.core.accounts import AuthResult
from qrksdock.net.session import SessionManager


class RemoteAuthProvider:
    def __init__(self, session: SessionManager):
        self.session = session

    def accounts(self) -> list[dict[str, str]]:
        return rules.roster()                                  # names and RCh. come from the app, so the tiles work offline

    def authenticate(self, initials: str, password: str) -> AuthResult:
        return self.session.login(initials, password)

    def change_password(self, initials: str, current: str, new: str) -> None:
        self.session.change_password(initials, current, new)

    def resume(self) -> str | None:
        return self.session.resume()

    def sign_out(self) -> None:
        self.session.sign_out()

    def describe(self) -> str:
        return f"Server: {self.session.api.host}"
