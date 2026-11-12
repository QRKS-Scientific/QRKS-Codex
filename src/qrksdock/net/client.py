"""A Supabase client for the QRKS app."""
from __future__ import annotations

from typing import Any
from supabase import create_client, Client
from gotrue.errors import AuthApiError

from qrksdock.net.errors import ApiError, Offline

class ApiClient:
    def __init__(self, supabase_url: str, supabase_key: str):
        if not supabase_url or not supabase_key:
            raise ValueError("Supabase URL and Anon Key are required.")
        self.supabase: Client = create_client(supabase_url, supabase_key)

    # ---- sign-in -----------------------------------------------------------------------------------------
    def login(self, email: str, password: str):
        try:
            res = self.supabase.auth.sign_in_with_password({"email": email, "password": password})
            return res
        except AuthApiError as e:
            raise ApiError(status=400, message=str(e))
        except Exception as e:
            raise Offline(f"Connection failed: {e}")

    def logout(self):
        self.supabase.auth.sign_out()

    def change_password(self, new_password: str):
        try:
            res = self.supabase.auth.update_user({"password": new_password})
            return res
        except AuthApiError as e:
            raise ApiError(status=400, message=str(e))

    def me(self):
        return self.supabase.auth.get_user()

    # ---- runs and events --------------------------------------------------------------------------------------
    def create_run(self, run_id: str, operator_id: str, manifest_hash: str = ""):
        data = {
            "run_id": run_id,
            "operator_id": operator_id,
            "manifest_hash": manifest_hash
        }
        res = self.supabase.table("runs").insert(data).execute()
        return res.data

    def list_runs(self):
        res = self.supabase.table("runs").select("*").execute()
        return res.data

    def post_events(self, run_id: str, operator_id: str, events: list[dict]):
        payloads = [
            {
                "run_id": run_id,
                "operator_id": operator_id,
                "event_type": ev.get("type", "unknown"),
                "timestamp": ev.get("timestamp"),
                "payload": ev
            }
            for ev in events
        ]
        res = self.supabase.table("events").insert(payloads).execute()
        return res.data