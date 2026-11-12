"""Where the session lives on the laptop: the operating system's keychain (macOS Keychain, Windows
Credential Manager). Never a plain file, never Qt settings."""
from __future__ import annotations

from typing import Protocol

SERVICE = "QRKSDock"


class SecretStore(Protocol):
    persistent: bool

    def get(self, name: str) -> str | None: ...
    def set(self, name: str, value: str) -> None: ...
    def delete(self, name: str) -> None: ...


class MemoryStore:
    """Nothing is written to disk. Used in tests and on systems with no keychain."""
    persistent = False

    def __init__(self) -> None:
        self._d: dict[str, str] = {}

    def get(self, name: str) -> str | None:
        return self._d.get(name)

    def set(self, name: str, value: str) -> None:
        self._d[name] = value

    def delete(self, name: str) -> None:
        self._d.pop(name, None)


class KeyringStore:
    persistent = True

    def __init__(self, service: str = SERVICE):
        import keyring
        self._kr, self._service = keyring, service

    def get(self, name: str) -> str | None:
        return self._kr.get_password(self._service, name)

    def set(self, name: str, value: str) -> None:
        self._kr.set_password(self._service, name, value)

    def delete(self, name: str) -> None:
        try:
            self._kr.delete_password(self._service, name)
        except Exception:                                            # noqa: BLE001  (already gone)
            pass


def default_store() -> SecretStore:
    """The OS keychain if it works, otherwise memory only (the session then ends when the app closes)."""
    try:
        store = KeyringStore(SERVICE + ".probe")
        store.set("probe", "ok")
        ok = store.get("probe") == "ok"
        store.delete("probe")
        if ok:
            return KeyringStore(SERVICE)
    except Exception:                                                # noqa: BLE001
        pass
    return MemoryStore()
