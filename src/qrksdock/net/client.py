"""A small, strict Supabase client for the QRKS server."""
from __future__ import annotations

from supabase import create_client, Client
from qrksdock.net.errors import Offline

class ApiClient:
    def __init__(self, supabase_url: str, supabase_anon_key: str):
        if not supabase_url or not supabase_anon_key:
            raise ValueError("Supabase URL and Anon Key are required.")
        self.host = supabase_url
        try:
            self.sb: Client = create_client(supabase_url, supabase_anon_key)
        except Exception as exc:
            raise Offline(f"Could not initialize Supabase: {exc}") from exc