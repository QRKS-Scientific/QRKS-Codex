"""The laptop side of the server connection, tested against a mocked server (no real network)."""
import json

import httpx
import pytest

from qrksdock.net.client import ApiClient
from qrksdock.net.errors import ApiError, Offline
from qrksdock.net.outbox import ALLOWED_FIELDS, Outbox, safe_data
from qrksdock.net.session import OFFLINE_MESSAGE, SessionManager
from qrksdock.net.store import MemoryStore
from qrksdock.net.sync import SyncService

URL = "https://qrks.example.org"
DAY = 86400


class Clock:
    def __init__(self, t=1_800_000_000.0):
        self.t = t

    def __call__(self):
        return self.t

    def advance(self, s):
        self.t += s


def api_with(handler):
    return ApiClient(URL, client=httpx.Client(transport=httpx.MockTransport(handler)))


def tokens(initials="LEM", refresh="r" * 30, must_change=False, expires=900):
    return {"access_token": "access-" + refresh[:6], "refresh_token": refresh, "token_type": "bearer", "expires_in": expires,
            "must_change": must_change, "user": {"initials": initials, "display_name": "Lars E. Medice, RCh.", "role": "Technical Lead"}}


def reply(status, body=None, headers=None):
    return httpx.Response(status, json=body if body is not None else {}, headers=headers)


def down(_request):
    raise httpx.ConnectError("no route to host")


# ---- the client --------------------------------------------------------------------------------------------------
def test_server_address_must_be_https_except_for_local_development():
    with pytest.raises(ValueError, match="https://"):
        ApiClient("http://qrks.example.org")
    ApiClient("https://qrks.example.org")
    ApiClient("http://localhost:8000")
    ApiClient("http://127.0.0.1:8000")
    with pytest.raises(ValueError):
        ApiClient("ftp://qrks.example.org")
    with pytest.raises(ValueError):
        ApiClient("not a url")


def test_network_failures_become_offline_and_http_errors_become_api_errors():
    with pytest.raises(Offline):
        api_with(down).meta()
    err = api_with(lambda r: reply(401, {"detail": {"code": "bad_credentials", "message": "Wrong password. 3 attempts left.", "attempts_left": 3}}))
    with pytest.raises(ApiError) as e:
        err.login("LEM", "x", "dev-1", "Mac")
    assert (e.value.status, e.value.code, e.value.attempts_left) == (401, "bad_credentials", 3)
    limited = api_with(lambda r: reply(429, {"detail": {"code": "rate_limited", "message": "Slow down."}}, {"Retry-After": "42"}))
    with pytest.raises(ApiError) as e:
        limited.meta()
    assert e.value.retry_after == 42
    with pytest.raises(ApiError) as e:                                        # a validation error shaped differently by the server
        api_with(lambda r: reply(422, {"detail": [{"loc": ["body"], "msg": "bad"}]})).meta()
    assert e.value.code == "invalid_request"


# ---- the session ----------------------------------------------------------------------------------------------------
def test_a_full_login_is_saved_but_a_temporary_one_is_not():
    store = MemoryStore()
    ok = SessionManager(api_with(lambda r: reply(200, tokens())), store, Clock())
    assert ok.login("LEM", "pw").ok and json.loads(store.get("session"))["initials"] == "LEM"
    store2 = MemoryStore()
    temp = SessionManager(api_with(lambda r: reply(200, tokens(must_change=True))), store2, Clock())
    res = temp.login("LEM", "pw")
    assert res.ok and res.must_change and store2.get("session") is None      # never saved until the password is changed


def test_login_errors_carry_the_servers_message_lock_time_and_attempts_left():
    s = SessionManager(api_with(lambda r: reply(401, {"detail": {"code": "bad_credentials", "message": "Wrong password. This account is locked for 30 s.",
                                                                 "retry_after": 30, "attempts_left": 0}})), MemoryStore(), Clock())
    r = s.login("LEM", "x")
    assert not r.ok and r.locked_for == 30 and r.attempts_left == 0 and "locked" in r.message
    off = SessionManager(api_with(down), MemoryStore(), Clock()).login("LEM", "x")
    assert not off.ok and off.message == OFFLINE_MESSAGE


def test_device_id_is_created_once_and_kept():
    store = MemoryStore()
    a = SessionManager(api_with(down), store, Clock()).device_id
    assert a.startswith("dev-") and len(a) >= 36 and SessionManager(api_with(down), store, Clock()).device_id == a


def test_resume_rotates_and_saves_the_new_refresh_token():
    store, clock = MemoryStore(), Clock()
    store.set("device_id", "dev-fixed-0001")
    store.set("session", json.dumps({"initials": "LEM", "refresh_token": "old" * 10, "last_verified": clock.t - DAY}))
    seen = {}

    def handler(req):
        seen["body"] = json.loads(req.content)
        return reply(200, tokens(refresh="new" * 10))
    s = SessionManager(api_with(handler), store, clock)
    assert s.resume() == "LEM" and not s.offline
    assert seen["body"] == {"refresh_token": "old" * 10, "device_id": "dev-fixed-0001"}
    saved = json.loads(store.get("session"))
    assert saved["refresh_token"] == "new" * 10 and saved["last_verified"] == clock.t     # the rotated token is what is kept


def test_seven_day_offline_grace():
    store, clock = MemoryStore(), Clock()
    store.set("session", json.dumps({"initials": "JER", "refresh_token": "t" * 30, "last_verified": clock.t}))
    clock.advance(6 * DAY + 23 * 3600)                                         # just inside the week
    s = SessionManager(api_with(down), store, clock)
    assert s.resume() == "JER" and s.offline and s.access() is None            # signed in, working offline
    assert store.get("session") is not None
    clock.advance(2 * 3600)                                                    # now past 7 days
    assert SessionManager(api_with(down), store, clock).resume() is None
    assert store.get("session") is None                                        # a fresh sign-in is now required


def test_a_session_the_server_no_longer_recognises_is_dropped():
    store = MemoryStore()
    store.set("session", json.dumps({"initials": "LEM", "refresh_token": "t" * 30, "last_verified": 1.0}))
    s = SessionManager(api_with(lambda r: reply(401, {"detail": {"code": "session_revoked", "message": "Sign in again."}})), store, Clock())
    assert s.resume() is None and store.get("session") is None


def test_corrupt_saved_sessions_are_ignored():
    store = MemoryStore()
    store.set("session", "{not json")
    assert SessionManager(api_with(down), store, Clock()).resume() is None and store.get("session") is None


def test_access_token_is_refreshed_before_it_expires_and_a_revoked_session_is_flagged():
    store, clock = MemoryStore(), Clock()
    calls = []

    def handler(req):
        calls.append(req.url.path)
        return reply(200, tokens(refresh=f"gen{len(calls)}" * 8))
    s = SessionManager(api_with(handler), store, clock)
    s.login("LEM", "pw")
    first = s.access_token
    assert s.access() == first and calls == ["/v1/auth/login"]                 # still fresh: no network call
    clock.advance(900 - 30)                                                    # inside the last minute
    assert s.access() != first and calls[-1] == "/v1/auth/refresh"
    revoked = SessionManager(api_with(lambda r: reply(401, {"detail": {"code": "session_revoked", "message": "x"}})), store, clock)
    revoked.refresh_token, revoked.access_exp = "t" * 30, 0
    assert revoked.access() is None and revoked.session_lost


def test_sign_out_revokes_on_the_server_and_always_wipes_the_keychain():
    store, calls = MemoryStore(), []
    s = SessionManager(api_with(lambda r: (calls.append(r.url.path), reply(200, tokens()))[1]), store, Clock())
    s.login("LEM", "pw")
    s.sign_out()
    assert "/v1/auth/logout" in calls and store.get("session") is None and not s.initials
    s2 = SessionManager(api_with(lambda r: reply(200, tokens())), MemoryStore(), Clock())
    s2.login("LEM", "pw")
    s2.api = api_with(down)                                                    # the server is unreachable at sign-out
    s2.sign_out()
    assert s2.store.get("session") is None


def test_changing_the_password_replaces_the_limited_session_and_saves_it():
    store, handlers = MemoryStore(), {"/v1/auth/login": tokens(must_change=True, refresh="a" * 30), "/v1/auth/change-password": tokens(refresh="b" * 30)}
    s = SessionManager(api_with(lambda r: reply(200, handlers[r.url.path])), store, Clock())
    s.login("LEM", "temp")
    s.change_password("LEM", "temp", "river-Stone-84-lamp")
    assert json.loads(store.get("session"))["refresh_token"] == "b" * 30
    bad = SessionManager(api_with(lambda r: reply(422, {"detail": {"code": "weak_password", "message": "Use at least 10 characters."}})), MemoryStore(), Clock())
    bad.access_token = "x"
    with pytest.raises(ValueError, match="at least 10"):
        bad.change_password("LEM", "temp", "short")


# ---- the outbox ----------------------------------------------------------------------------------------------------------
def test_the_outbox_only_ever_holds_allowed_fields():
    assert safe_data("ligand_renamed", {"from": "client-compound", "to": "CCO"}) == {}
    assert safe_data("ligands_prepared", {"ligands": 3, "states": 4, "smiles": "CCO", "names": ["x"]}) == {"ligands": 3, "states": 4}
    assert safe_data("run_completed", {"run_id": "A1", "ligands": 2, "vina": "1.2.7", "best_affinity": -9.9}) == {"run_id": "A1", "ligands": 2, "vina": "1.2.7"}
    assert safe_data("receptor_prepared", {"method": "x", "ph": 7.4, "box": {"nested": "dict"}}) == {"method": "x", "ph": 7.4}


def test_outbox_queue_dedupes_orders_and_skips_unshared_activity(tmp_path):
    ob = Outbox(tmp_path / "o.sqlite")
    a = ob.enqueue("QDOCK-260824-001", "QC-001", "run_created", {"package": "Hadron"}, "2026-11-08T01:00:00+00:00", event_id="id-one-0001")
    ob.enqueue("QDOCK-260824-001", "QC-001", "run_created", {"package": "Hadron"}, "2026-11-08T01:00:00+00:00", event_id="id-one-0001")
    ob.enqueue("QDOCK-260824-001", "QC-001", "receptor_prepared", {"method": "pdb2pqr"}, "2026-11-08T01:01:00+00:00")
    assert ob.enqueue("QDOCK-260824-001", "QC-001", "private_note", {"x": 1}, "2026-11-08T01:02:00+00:00") is None
    assert ob.count() == 2 and [p.kind for p in ob.pending()] == ["run_created", "receptor_prepared"]
    ob.mark([a], 1)
    assert ob.count() == 1
    assert Outbox(tmp_path / "o.sqlite").count() == 1                          # survives a restart


def test_every_shared_event_type_matches_the_servers_allowlist():
    from pathlib import Path
    src = (Path(__file__).resolve().parents[1] / "server" / "app" / "schemas.py").read_text()
    for kind, fields in ALLOWED_FIELDS.items():
        assert f'"{kind}": ' in src
        for f in fields:
            assert f'"{f}"' in src


# ---- the sync service ---------------------------------------------------------------------------------------------------
def signed_in_service(tmp_path, handler):
    store, clock = MemoryStore(), Clock()
    api = api_with(handler)
    session = SessionManager(api, store, clock)
    session.access_token, session.access_exp, session.refresh_token = "tok", clock.t + 900, "r" * 30
    outbox = Outbox(tmp_path / "o.sqlite")
    return SyncService(api, session, outbox), outbox


def queue(outbox, n=2, run="QDOCK-260824-001", client="QC-001"):
    for i in range(n):
        outbox.enqueue(run, client, "receptor_prepared", {"method": "pdb2pqr"}, f"2026-11-08T01:0{i}:00+00:00", event_id=f"ev-{run[-3:]}-{i:04d}")


def test_flush_uploads_and_marks_sent(tmp_path):
    svc, ob = signed_in_service(tmp_path, lambda r: reply(200, {"accepted": 2, "duplicates": 0, "fields_dropped": 0}))
    queue(ob)
    res = svc.flush()
    assert res.sent == 2 and res.pending == 0 and res.online and ob.count() == 0


def test_flush_offline_keeps_everything_for_later(tmp_path):
    svc, ob = signed_in_service(tmp_path, down)
    queue(ob, 3)
    res = svc.flush()
    assert not res.online and res.sent == 0 and res.pending == 3 and ob.count() == 3


def test_flush_registers_an_unknown_run_then_retries(tmp_path):
    calls = []

    def handler(req):
        calls.append((req.method, req.url.path))
        if req.url.path.endswith("/events") and calls.count(("POST", req.url.path)) == 1:
            return reply(404, {"detail": {"code": "unknown_run", "message": "not registered"}})
        return reply(200, {"accepted": 1})
    svc, ob = signed_in_service(tmp_path, handler)
    queue(ob, 1, run="QDOCK-260824-007", client="QC-007")
    assert svc.flush().sent == 1
    assert ("POST", "/v1/runs") in calls and calls.count(("POST", "/v1/runs/QDOCK-260824-007/events")) == 2


def test_rejected_events_are_not_retried_forever_but_auth_problems_are_kept(tmp_path):
    svc, ob = signed_in_service(tmp_path, lambda r: reply(422, {"detail": {"code": "bad_time", "message": "bad time"}}))
    queue(ob, 2)
    res = svc.flush()
    assert ob.count() == 0 and "rejected" in res.message                        # parked, not retried every 30 seconds
    svc2, ob2 = signed_in_service(tmp_path / "b", lambda r: reply(401, {"detail": {"code": "token_expired", "message": "expired"}}))
    queue(ob2, 2)
    assert svc2.flush().pending == 2                                           # an auth problem keeps the events


def test_creating_a_run_offline_raises_offline_and_online_returns_the_servers_code(tmp_path):
    svc, _ = signed_in_service(tmp_path, down)
    with pytest.raises(Offline):
        svc.create_run("QC-001")
    svc2, _ = signed_in_service(tmp_path / "b", lambda r: reply(200, {"code": "QDOCK-260824-003", "client_code": "QC-001"}))
    assert svc2.create_run("QC-001") == "QDOCK-260824-003"
