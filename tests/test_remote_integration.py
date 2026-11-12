"""Live integration test against Supabase (skipped unless QRKS_TEST_PASSWORD is set)."""
from __future__ import annotations

import os

import pytest

from qrksdock.net.config import supabase_credentials
from qrksdock.net.services import NetServices
from qrksdock.net.store import MemoryStore

_URL, _KEY = supabase_credentials()
_TEST_EMAIL = os.environ.get("QRKS_TEST_EMAIL", "lem@qrks.com")
_TEST_PASSWORD = os.environ.get("QRKS_TEST_PASSWORD", "")

pytestmark = pytest.mark.skipif(
    not (_URL and _KEY and _TEST_PASSWORD),
    reason="Set QRKS_TEST_PASSWORD (and Supabase credentials) to run live Supabase integration tests.",
)


def test_live_supabase_auth_and_session_cycle(tmp_path):
    services = NetServices.create(store=MemoryStore(), outbox_path=tmp_path / "live_outbox.sqlite")
    assert services is not None

    auth_res = services.session.login(_TEST_EMAIL, _TEST_PASSWORD)
    assert auth_res.ok is True, auth_res.message
    assert services.session.access() is not None

    services.session.sign_out()
    assert services.session.access() is None