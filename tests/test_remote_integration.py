"""The laptop code against the real server, running in-process. Skipped automatically if the server's
packages (fastapi, sqlalchemy, argon2, pyjwt) are not installed."""
import json
import os
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from qrksdock.core import rules
from qrksdock.core.runs import Run
from qrksdock.net.errors import Offline
from qrksdock.net.provider import RemoteAuthProvider
from qrksdock.net.services import NetServices
from qrksdock.net.session import SessionManager
from qrksdock.net.store import MemoryStore

SERVER = Path(__file__).resolve().parents[1] / "server"
NEW_PASSWORD = "river-Stone-84-lamp"


class FlakyClient:
    """Wraps the in-process server client so a test can switch the 'internet' off and on."""
    def __init__(self, inner):
        self.inner, self.down = inner, False

    def request(self, *a, **k):
        if self.down:
            raise httpx.ConnectError("offline")
        return self.inner.request(*a, **k)


@pytest.fixture()
def server(tmp_path):
    for mod in ("fastapi", "argon2", "sqlalchemy", "jwt", "pydantic_settings"):
        pytest.importorskip(mod)
    if str(SERVER) not in sys.path:
        sys.path.insert(0, str(SERVER))
    from fastapi.testclient import TestClient
    from app.admin import create_users
    from app.config import Settings
    from app.main import create_app
    settings = Settings(database_url=f"sqlite:///{tmp_path}/server.db", jwt_secret="s" * 40, argon2_time_cost=1, argon2_memory_kib=64,
                        login_rate_per_minute=1000, api_rate_per_minute=100000)
    app = create_app(settings)
    roster = json.loads((SERVER / "roster.json").read_text(encoding="utf-8"))
    with app.state.sessionmaker() as db:
        passwords = create_users(db, app.state.security, settings, roster, time.time())
    return SimpleNamespace(app=app, client=FlakyClient(TestClient(app)), raw=TestClient(app), passwords=passwords)


def services(server, tmp_path, store=None, name="outbox"):
    return NetServices.create("http://testserver", store=store or MemoryStore(), client=server.client,
                              outbox_path=tmp_path / f"{name}.sqlite", allow_insecure=True)


def full_sign_in(svc, server, ini="LEM"):
    prov = RemoteAuthProvider(svc.session)
    first = prov.authenticate(ini, server.passwords[ini])
    assert first.ok and first.must_change
    prov.change_password(ini, server.passwords[ini], NEW_PASSWORD)
    return prov


def server_events(server, svc, code):
    return server.raw.get(f"/v1/runs/{code}/events", headers={"Authorization": f"Bearer {svc.session.access()}"}).json()["events"]


def test_server_roster_matches_the_apps_roster_including_rch():
    roster = json.loads((SERVER / "roster.json").read_text(encoding="utf-8"))
    assert roster == [{"initials": p["initials"], "display_name": p["display_name"], "role": p["role"]} for p in rules.roster()]
    assert all(p["display_name"].endswith(", RCh.") for p in roster)


def test_first_sign_in_then_resume_then_sign_out(server, tmp_path):
    store = MemoryStore()
    svc = services(server, tmp_path, store)
    full_sign_in(svc, server)
    assert svc.session.display_name == "Lars E. Medice, RCh." and store.get("session")
    again = SessionManager(svc.api, store)                       # the app is closed and reopened on the same laptop
    assert again.resume() == "LEM" and not again.offline
    again.sign_out()
    assert SessionManager(svc.api, store).resume() is None       # no saved session remains


def test_the_temporary_password_is_dead_on_every_other_laptop(server, tmp_path):
    full_sign_in(services(server, tmp_path, MemoryStore(), "a"), server)
    second = RemoteAuthProvider(services(server, tmp_path, MemoryStore(), "b").session)
    res = second.authenticate("LEM", server.passwords["LEM"])
    assert not res.ok and "Wrong" in res.message


def test_lockout_reaches_the_sign_in_screen_message(server, tmp_path):
    prov = RemoteAuthProvider(services(server, tmp_path).session)
    results = [prov.authenticate("JER", "wrong") for _ in range(5)]
    assert [r.attempts_left for r in results[:4]] == [4, 3, 2, 1] and results[4].locked_for == 30
    assert prov.authenticate("JER", server.passwords["JER"]).locked_for > 0


def test_a_run_travels_from_the_laptop_to_the_server_without_any_chemistry(server, tmp_path):
    svc = services(server, tmp_path)
    full_sign_in(svc, server, "JCG")
    Run.event_sink = lambda run, e: svc.outbox.enqueue(run.code, run.client, e["type"], e["data"], e["utc"])
    code = svc.create_run("QC-001", "Hadron")                    # the server issues the code
    run = Run.create(tmp_path / "runs", "QC-001", "JCG", "Hadron", qdock_code=code)
    run.log("JCG", "receptor_prepared", {"method": "pdb2pqr", "ph": 7.4, "box": "blind"})
    run.log("JCG", "ligand_renamed", {"from": "client-compound-7", "to": "CC(=O)Nc1ccc(O)cc1"})
    run.log("JCG", "private_note", {"text": "not shared"})
    res = svc.sync.flush()
    assert res.sent == 3 and res.pending == 0 and res.online
    events = server_events(server, svc, code)
    assert {e["type"] for e in events} == {"run_created", "receptor_prepared", "ligand_renamed"}
    assert {e["actor"] for e in events} == {"JCG"}
    blob = json.dumps(events)
    assert "client-compound" not in blob and "CC(=O)" not in blob and "not shared" not in blob
    assert svc.sync.flush().sent == 0                              # nothing is sent twice
    assert len(run.activity()) == 4                                # the local activity.jsonl keeps everything, including the private note


def test_a_run_folder_created_before_the_server_knew_it_is_registered_on_first_upload(server, tmp_path):
    svc = services(server, tmp_path)
    full_sign_in(svc, server)
    Run.event_sink = lambda run, e: svc.outbox.enqueue(run.code, run.client, e["type"], e["data"], e["utc"])
    Run.create(tmp_path / "runs", "QC-007", "LEM", qdock_code="QDOCK-260824-007")      # as if made by hand on Drive
    assert svc.sync.flush().sent == 1
    runs = server.raw.get("/v1/runs", headers={"Authorization": f"Bearer {svc.session.access()}"}).json()["runs"]
    assert [(r["code"], r["client_code"]) for r in runs] == [("QDOCK-260824-007", "QC-007")]


def test_working_offline_then_catching_up(server, tmp_path):
    svc = services(server, tmp_path)
    full_sign_in(svc, server)
    code = svc.create_run("QC-001")
    Run.event_sink = lambda run, e: svc.outbox.enqueue(run.code, run.client, e["type"], e["data"], e["utc"])
    run = Run.create(tmp_path / "runs", "QC-001", "LEM", qdock_code=code)
    server.client.down = True                                      # the internet goes away
    run.log("LEM", "receptor_prepared", {"method": "pdb2pqr"})
    run.log("LEM", "ligands_prepared", {"ligands": 4, "states": 4})
    res = svc.sync.flush()
    assert not res.online and res.pending == 3
    with pytest.raises(Offline):
        svc.create_run("QC-002")                                   # new runs need the server so codes stay unique
    server.client.down = False                                     # and comes back
    res = svc.sync.flush()
    assert res.online and res.sent == 3 and res.pending == 0
    assert {e["type"] for e in server_events(server, svc, code)} == {"run_created", "receptor_prepared", "ligands_prepared"}


def test_the_seven_day_grace_against_the_real_server(server, tmp_path):
    store = MemoryStore()
    clock = SimpleNamespace(t=time.time())
    now = lambda: clock.t
    svc = NetServices.create("http://testserver", store=store, client=server.client, outbox_path=tmp_path / "o.sqlite", clock=now, allow_insecure=True)
    full_sign_in(svc, server)
    server.client.down = True
    clock.t += 6 * 86400
    offline = SessionManager(svc.api, store, now)
    assert offline.resume() == "LEM" and offline.offline
    clock.t += 2 * 86400
    assert SessionManager(svc.api, store, now).resume() is None


# ---- the window -----------------------------------------------------------------------------------------------------------------
def pump(app, cond, seconds=6.0):
    end = time.time() + seconds
    while time.time() < end:
        app.processEvents()
        if cond():
            return True
        time.sleep(0.02)
    return False


def test_the_whole_app_against_the_server(server, tmp_path, monkeypatch):
    pytest.importorskip("PySide6")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QDialog, QMessageBox
    from test_app import _app
    from qrksdock.gui.app import MainWindow
    from qrksdock.gui.login import ChangePasswordDialog
    app = _app()
    store = MemoryStore()
    svc = services(server, tmp_path, store)
    win = MainWindow(settings=QSettings(str(tmp_path / "qt.ini"), QSettings.IniFormat), services=svc)
    win.show()
    assert win.root_stack.currentIndex() == 0 and not win.sync_chip.isVisible()
    assert [t for t in win.login.tiles] == ["LEM", "JER", "LPA", "JCG", "JML", "ERD"]       # tiles come from the app's roster

    def fake_exec(self):
        self.new.setText(NEW_PASSWORD)
        self.again.setText(NEW_PASSWORD)
        self._save()
        return self.result()
    monkeypatch.setattr(ChangePasswordDialog, "exec", fake_exec)
    win.login._select("LEM")
    win.login.password.setText(server.passwords["LEM"])
    win.login._submit()
    assert win.root_stack.currentIndex() == 1 and win.operator == "LEM" and win.user_name.text() == "Lars E. Medice, RCh."
    assert pump(app, lambda: win.sync_chip.text().startswith("Online"))

    page = win.pages[0]
    page.root_edit.setText(str(tmp_path / "runs"))
    page.client_edit.setText("qc-1")
    page._new()                                                                                # the server issues the QDOCK code
    assert win.run is not None and win.run.client == "QC-001" and win.run.path.parent.name == "QC-001"
    win.run.log("LEM", "receptor_prepared", {"method": "pdb2pqr", "ph": 7.4, "box": "blind"})
    win._sync_now()
    assert pump(app, lambda: svc.outbox.count() == 0)
    token = {"Authorization": f"Bearer {svc.session.access()}"}
    on_server = server.raw.get("/v1/runs", headers=token).json()["runs"]
    assert [r["code"] for r in on_server] == [win.run.code] and on_server[0]["stage"] == "receptor ready"

    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: warnings.append(a[2]))
    server.client.down = True                                                                  # internet off
    win.run.log("LEM", "ligands_prepared", {"ligands": 2, "states": 2})
    win._sync_now()
    assert pump(app, lambda: win.sync_chip.text().startswith("Offline"))
    assert "1 waiting" in win.sync_chip.text()
    runs_before = len(list((tmp_path / "runs").glob("QC-*/QDOCK-*")))
    page.client_edit.setText("QC-002")
    page._new()
    assert warnings and "connection" in warnings[0] and len(list((tmp_path / "runs").glob("QC-*/QDOCK-*"))) == runs_before
    server.client.down = False

    win.sign_out()
    assert win.root_stack.currentIndex() == 0 and not win.sync_chip.isVisible() and store.get("session") is None
    win.login._select("LEM")
    win.login.password.setText(NEW_PASSWORD)
    win.login._submit()
    assert win.root_stack.currentIndex() == 1                                                  # own password now works
    win.close()

    # reopening the app on the same laptop signs the lead straight back in
    svc2 = services(server, tmp_path, store, "outbox2")
    win2 = MainWindow(settings=QSettings(str(tmp_path / "qt2.ini"), QSettings.IniFormat), services=svc2)
    win2.show()
    assert pump(app, lambda: win2.root_stack.currentIndex() == 1) and win2.operator == "LEM"
    win2.close()


def test_events_queued_during_an_upload_follow_straight_away(server, tmp_path):
    pytest.importorskip("PySide6")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QSettings
    from test_app import _app
    from qrksdock.gui.app import MainWindow
    from qrksdock.net.sync import SyncResult
    app = _app()
    svc = services(server, tmp_path)
    win = MainWindow(settings=QSettings(str(tmp_path / "qt.ini"), QSettings.IniFormat), services=svc)
    calls = []
    win._sync_now = lambda: calls.append(1)
    svc.outbox.enqueue("QDOCK-260824-001", "QC-001", "run_created", {}, "2026-11-08T01:00:00+00:00")
    win._sync_done(SyncResult(sent=0, pending=0, online=True))        # the sync saw nothing, but an event arrived meanwhile
    pump(app, lambda: bool(calls), 1.0)
    assert calls == [1]
    win._sync_done(SyncResult(sent=0, pending=1, online=True))        # nothing new and no progress (for example a refused login): do NOT spin
    win._sync_done(SyncResult(sent=0, pending=0, online=False))       # offline: wait for the timer instead
    pump(app, lambda: False, 0.5)
    assert calls == [1]
    win._sync_done(SyncResult(sent=3, pending=1, online=True))        # progress with more to send: go again
    pump(app, lambda: len(calls) == 2, 1.0)
    assert calls == [1, 1]
    win.close()
