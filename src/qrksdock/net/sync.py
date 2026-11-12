"""Uploads queued events and asks the server for run codes via Supabase SDK."""
from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import dataclass

from qrksdock.net.client import ApiClient
from qrksdock.net.errors import Offline
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
        """Create a new run directly in the Supabase 'runs' table."""
        if not self.session.access():
            raise Offline("no session")
        
        run_code = f"QDOCK-{uuid.uuid4().hex[:6].upper()}"
        data = {
            "code": run_code,
            "client_code": client_code,
            "package": package
        }
        
        response = self.api.sb.table("runs").insert(data).execute()
        if response.data:
            return response.data[0]["code"]
        raise Exception("Failed to create run in Supabase")

    def flush(self) -> SyncResult:
        result = SyncResult(pending=self.outbox.count())
        if not result.pending:
            result.online = self.session.access() is not None or not self.session.offline
            return result
        
        if not self.session.access():
            result.online = False
            result.message = "Offline: events will upload when the connection returns."
            return result
            
        by_run = defaultdict(list)
        for p in self.outbox.pending():
            by_run[p.run_code].append(p)
            
        for code, items in by_run.items():
            payload = [{"id": p.id, "run_code": code, "type": p.kind, "utc": p.utc, "data": p.data} for p in items]
            try:
                self.api.sb.table("events").insert(payload).execute()
                self.outbox.mark([p.id for p in items], 1)
                result.sent += len(items)
            except Exception as exc:
                self.outbox.mark([p.id for p in items], 2)
                result.message = f"Some events were rejected: {str(exc)}"
                
        result.pending = self.outbox.count()
        return result