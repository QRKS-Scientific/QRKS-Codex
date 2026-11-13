"""Unit tests for the Supabase networking, session, and outbox sync layer."""
from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from qrksdock.net import client as client_mod
from qrksdock.net.config import supabase_credentials
from qrksdock.net.errors import Offline
from qrksdock.net.outbox import Outbox
from qrksdock.net.provider import RemoteAuthProvider
from qrksdock.net.services import NetServices
from qrksdock.net.session import SessionManager
from qrksdock.net.store import MemoryStore
from qrksdock.net.sync import SyncService


def _fake_supabase() -> MagicMock:
    sb = MagicMock()
    session_obj = SimpleNamespace(access_token="tok_access_123", refresh_token="tok_refresh_456")
    sb.auth.sign_in_with_password.return_value = SimpleNamespace(session=session_obj)
    sb.auth.get_session.return_value = session_obj

    def _table_side_effect(table_name: str):
        tbl = MagicMock()
        if table_name == "runs":
            tbl.insert.return_value.execute.side_effect = lambda: SimpleNamespace(
                data=[{"code": tbl.insert.call_args[0][0]["code"]}]
            )
        else:
            tbl.insert.return_value.execute.return_value = SimpleNamespace(data=[{"ok": True}])
        return tbl

    sb.table.side_effect = _table_side_effect
    return sb


@pytest.fixture
def fake_api(monkeypatch):
    sb = _fake_supabase()
    monkeypatch.setattr(client_mod, "create_client", lambda url, key: sb)
    api = client_mod.ApiClient("https://example.supabase.co", "anon-test-key")
    return api, sb


def test_supabase_credentials_from_env(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://env-test.supabase.co")
    monkeypatch.setenv("SUPABASE_ANON_KEY", "env-anon-key")
    url, key = supabase_credentials()
    assert url == "https://env-test.supabase.co"
    assert key == "env-anon-key"


def test_login_persists_session_and_maps_initials(fake_api):
    api, sb = fake_api
    store = MemoryStore()
    sm = SessionManager(api, store, clock=lambda: 1000.0)

    res = sm.login("lem@qrks.com", "correct-horse-battery-staple")
    assert res.ok is True
    assert sm.initials == "LEM"
    assert sm.access() == "tok_access_123"
    sb.auth.sign_in_with_password.assert_called_once_with(
        {"email": "lem@qrks.com", "password": "correct-horse-battery-staple"}
    )

    session = store.get("session")
    assert session is not None
    saved = json.loads(session)
    assert saved["initials"] == "LEM"
    assert saved["access_token"] == "tok_access_123"
    assert saved["refresh_token"] == "tok_refresh_456"


def test_resume_and_sign_out(fake_api):
    api, sb = fake_api
    store = MemoryStore()
    sm1 = SessionManager(api, store)
    sm1.login("jer@qrks.com", "secret-pass")

    sm2 = SessionManager(api, store)
    assert sm2.resume() == "JER"

    provider = RemoteAuthProvider(sm2)
    assert provider.describe() == "Server: https://example.supabase.co"
    provider.sign_out()

    assert store.get("session") is None
    sb.auth.sign_out.assert_called()


def test_create_run_and_flush_outbox(fake_api, tmp_path):
    api, sb = fake_api
    store = MemoryStore()
    sm = SessionManager(api, store)
    outbox = Outbox(tmp_path / "outbox.sqlite")
    sync = SyncService(api, sm, outbox)

    # Unauthenticated run creation raises Offline
    sb.auth.get_session.return_value = None
    with pytest.raises(Offline):
        sync.create_run("QC-001", "Hadron")

    # Authenticate and create run
    sb.auth.get_session.return_value = SimpleNamespace(access_token="tok_1", refresh_token="ref_1")
    sm.login("lem@qrks.com", "secret-pass")
    run_code = sync.create_run("QC-001", "Hadron")
    assert run_code.startswith("QDOCK-")

    # Enqueue allowed event (sensitive fields like smiles must be stripped by outbox)
    outbox.enqueue(
        run_code,
        "QC-001",
        "ligands_prepared",
        {"ligands": 5, "states": 8, "smiles": "CCO"},
        "2026-11-12T12:00:00Z",
    )
    assert outbox.count() == 1

    result = sync.flush()
    assert result.online is True
    assert result.sent == 1
    assert result.pending == 0


def test_net_services_factory(monkeypatch, tmp_path):
    sb = _fake_supabase()
    monkeypatch.setattr(client_mod, "create_client", lambda url, key: sb)
    monkeypatch.setenv("SUPABASE_URL", "https://factory.supabase.co")
    monkeypatch.setenv("SUPABASE_ANON_KEY", "factory-key")

    services = NetServices.create(store=MemoryStore(), outbox_path=tmp_path / "ob.sqlite")
    assert services is not None
    assert services.api.host == "https://factory.supabase.co"