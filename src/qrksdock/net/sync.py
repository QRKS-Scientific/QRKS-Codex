"""Uploads queued events and asks the server for run codes."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from qrksdock.net.client import ApiClient
from qrksdock.net.errors import ApiError, NetError, Offline
from qrksdock.net.outbox import Outbox
from qrksdock.net.session import SessionManager


@dataclass
class SyncResult:
    sent: int = 0
    pending: int = 0
    online: bool = True
    message: str = ""


class SyncService:
    def __init__(self, api: ApiClient, session: SessionManager, outbox: Outbox):
        self.api, self.session, self.outbox = api, session, outbox

    def create_run(self, client_code: str, package: str = "") -> str:
        """Ask the server for the next QDOCK code. Raises Offline when there is no connection."""
        token = self.session.access()
        if token is None:
            raise Offline("no session")
        return self.api.create_run(token, client_code, package)["code"]

    def flush(self) -> SyncResult:
        result = SyncResult(pending=self.outbox.count())
        if not result.pending:
            result.online = self.session.access() is not None or not self.session.offline
            return result
        token = self.session.access()
        if token is None:
            result.online = False
            result.message = "Offline: events will upload when the connection returns."
            return result
        by_run: dict[str, list] = defaultdict(list)
        for p in self.outbox.pending():
            by_run[p.run_code].append(p)
        for code, items in by_run.items():
            payload = [{"id": p.id, "type": p.kind, "utc": p.utc, "data": p.data} for p in items]
            try:
                try:
                    self.api.post_events(token, code, payload)
                except ApiError as exc:
                    if exc.code != "unknown_run":
                        raise
                    self.api.create_run(token, items[0].client_code, code=code)        # a folder created before the server knew it
                    self.api.post_events(token, code, payload)
                self.outbox.mark([p.id for p in items], 1)
                result.sent += len(items)
            except Offline:
                result.online, result.message = False, "Offline: events will upload when the connection returns."
                break
            except ApiError as exc:
                if exc.status in (401, 403):
                    result.message = exc.message
                    break
                self.outbox.mark([p.id for p in items], 2)                              # the server refused them; do not retry forever
                result.message = f"Some events were rejected: {exc.message}"
            except NetError as exc:
                result.message = str(exc)
                break
        result.pending = self.outbox.count()
        return result
