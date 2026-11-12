"""Pre-made accounts for the six company leads. There is no registration.

How it works
  * `data/accounts.json` ships with the app and holds, for each lead, a salted PBKDF2 hash of a
    temporary password. No password is stored in readable form anywhere.
  * The first time a lead signs in on a laptop, they must choose their own password. The new hash
    is stored in that laptop's settings folder and replaces the temporary one on that laptop.
  * Repeated wrong passwords lock the account for a short, growing time.

What it is, honestly: a gate that stops casual use and records who is working. It is not
protection against someone who has the installer and unlimited time. Real protection for client
data comes from Google Drive permissions and disk encryption.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from qrksdock import paths
from qrksdock.core import rules

ITERATIONS = 600_000
MIN_PASSWORD_LENGTH = 10
MAX_FREE_ATTEMPTS = 5
BASE_LOCK_SECONDS = 30
MAX_LOCK_SECONDS = 900


def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def _derive(password: str, salt: bytes, iterations: int) -> bytes:
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations, dklen=32)


def hash_password(password: str, iterations: int = ITERATIONS) -> dict[str, Any]:
    salt = os.urandom(16)
    return {"salt": _b64(salt), "hash": _b64(_derive(password, salt, iterations)), "iterations": iterations}


def check_password(password: str, record: dict[str, Any]) -> bool:
    expected = base64.b64decode(record["hash"])
    got = _derive(password, base64.b64decode(record["salt"]), int(record["iterations"]))
    return hmac.compare_digest(expected, got)


def password_problem(new_password: str, current_password: str = "", initials: str = "") -> str | None:
    """Return a plain-language reason the password is not acceptable, or None."""
    if len(new_password) < MIN_PASSWORD_LENGTH:
        return f"Use at least {MIN_PASSWORD_LENGTH} characters."
    if new_password == current_password:
        return "The new password must be different from the temporary one."
    if len(set(new_password)) < 4:
        return "Use a more varied password."
    low = new_password.lower()
    if initials and initials.lower() in low:
        return "Do not put your initials in your password."
    return None


@dataclass
class AuthResult:
    ok: bool
    must_change: bool = False
    message: str = ""
    locked_for: int = 0            # seconds until another attempt is allowed
    attempts_left: int | None = None


class AccountStore:
    def __init__(self, shipped_file: Path | None = None, local_dir: Path | None = None,
                 clock: Callable[[], float] = time.time):
        self.shipped_file = shipped_file or paths.data_file("accounts.json")
        self.local_dir = Path(local_dir) if local_dir else paths.user_data_dir()
        self.clock = clock

    # ---- files ----------------------------------------------------------------------------------------
    @property
    def _cred_file(self) -> Path:
        return self.local_dir / "credentials.json"

    @property
    def _attempt_file(self) -> Path:
        return self.local_dir / "login_attempts.json"

    def _read(self, path: Path) -> dict[str, Any]:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    def _write(self, path: Path, data: dict[str, Any]) -> None:
        self.local_dir.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f".{path.name}.tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        os.replace(tmp, path)

    def _shipped(self) -> dict[str, Any]:
        return self._read(self.shipped_file).get("accounts", {})

    # ---- who can sign in ---------------------------------------------------------------------------------
    def accounts(self) -> list[dict[str, str]]:
        """The leads from the roster who have a credential record, in roster order."""
        have = self._shipped()
        return [p for p in rules.roster() if p["initials"] in have]

    def needs_password_change(self, initials: str) -> bool:
        return initials not in self._read(self._cred_file)

    # ---- sign in -----------------------------------------------------------------------------------------------
    def _lock_remaining(self, initials: str) -> int:
        rec = self._read(self._attempt_file).get(initials, {})
        return max(0, int(rec.get("locked_until", 0) - self.clock()))

    def authenticate(self, initials: str, password: str) -> AuthResult:
        wait = self._lock_remaining(initials)
        if wait:
            return AuthResult(False, message=f"Too many wrong passwords. Try again in {wait} s.", locked_for=wait)
        local = self._read(self._cred_file).get(initials)
        shipped = self._shipped().get(initials)
        record, must_change = (local, False) if local else (shipped, True)
        if record is None:
            return AuthResult(False, message="This account does not exist.")
        if password and check_password(password, record):
            attempts = self._read(self._attempt_file)
            if initials in attempts:
                attempts.pop(initials)
                self._write(self._attempt_file, attempts)
            return AuthResult(True, must_change=must_change)
        attempts = self._read(self._attempt_file)
        fails = int(attempts.get(initials, {}).get("fails", 0)) + 1
        rec: dict[str, Any] = {"fails": fails}
        if fails >= MAX_FREE_ATTEMPTS:
            lock = min(BASE_LOCK_SECONDS * 2 ** (fails - MAX_FREE_ATTEMPTS), MAX_LOCK_SECONDS)
            rec["locked_until"] = self.clock() + lock
            attempts[initials] = rec
            self._write(self._attempt_file, attempts)
            return AuthResult(False, message=f"Wrong password. This account is locked for {lock} s.", locked_for=lock, attempts_left=0)
        attempts[initials] = rec
        self._write(self._attempt_file, attempts)
        left = MAX_FREE_ATTEMPTS - fails
        return AuthResult(False, message=f"Wrong password. {left} attempt{'s' if left != 1 else ''} left before a short lock.", attempts_left=left)

    # ---- the AuthProvider interface (shared with RemoteAuthProvider) ----------------------------------------------
    def resume(self) -> str | None:
        return None                                            # local accounts have no saved session

    def sign_out(self) -> None:
        return None

    def describe(self) -> str:
        return "Local accounts (development mode)"

    # ---- password change ---------------------------------------------------------------------------------------------
    def change_password(self, initials: str, current_password: str, new_password: str) -> None:
        problem = password_problem(new_password, current_password, initials)
        if problem:
            raise ValueError(problem)
        local = self._read(self._cred_file).get(initials)
        record = local or self._shipped().get(initials)
        if record is None or not check_password(current_password, record):
            raise ValueError("The current password is not correct.")
        creds = self._read(self._cred_file)
        creds[initials] = hash_password(new_password)
        self._write(self._cred_file, creds)
