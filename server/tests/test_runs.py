import json
import threading
from concurrent.futures import ThreadPoolExecutor

from fastapi.testclient import TestClient

from conftest import Clock, DEVICE, build_env

UUID = "evt-{:04d}-aaaa-bbbb"


def signed(env, ini="LEM", device=DEVICE):
    return env.auth(env.sign_in_fully(ini, device=device)["access_token"])


def test_codes_are_issued_in_sequence_across_clients(env):
    h = signed(env)
    codes = [env.client.post("/v1/runs", headers=h, json={"client_code": c}).json()["code"] for c in ("QC-001", "QC-002", "QC-001")]
    assert [c[-3:] for c in codes] == ["001", "002", "003"] and len({c[:13] for c in codes}) == 1
    assert codes[0].startswith("QDOCK-261108-")                            # 21:20 UTC is already 08 Nov in Manila (UTC+8)


def test_code_date_follows_the_manila_calendar_day(tmp_path):
    e = build_env(tmp_path)
    e.clock.t = 1794013200.0         # 01:00 UTC on 07 Nov = 09:00 in Manila
    h = signed(e)
    assert e.client.post("/v1/runs", headers=h, json={"client_code": "QC-001"}).json()["code"] == "QDOCK-261107-001"
    e.clock.advance(15 * 3600)                                             # 16:00 UTC = 00:00 on 08 Nov in Manila
    h = e.auth(e.login("LEM", "river-Stone-84-lamp").json()["access_token"])   # the 15-minute access token has expired by now
    assert e.client.post("/v1/runs", headers=h, json={"client_code": "QC-001"}).json()["code"] == "QDOCK-261108-001"


def test_two_laptops_creating_runs_at_once_never_get_the_same_code(tmp_path):
    e = build_env(tmp_path)
    heads = [signed(e, ini, device=f"laptop-{ini}-000000") for ini in ("LEM", "JER", "JCG", "JML")]
    results, lock = [], threading.Lock()

    def make(i):
        c = TestClient(e.app)
        r = c.post("/v1/runs", headers=heads[i % 4], json={"client_code": f"QC-{i % 3 + 1:03d}"})
        with lock:
            results.append(r)

    with ThreadPoolExecutor(8) as pool:
        list(pool.map(make, range(24)))
    assert all(r.status_code == 200 for r in results)
    codes = [r.json()["code"] for r in results]
    assert len(set(codes)) == 24 and sorted(c[-3:] for c in codes) == [f"{n:03d}" for n in range(1, 25)]


def test_a_retried_create_returns_the_same_run(env):
    h = signed(env)
    a = env.client.post("/v1/runs", headers=h, json={"client_code": "QC-001", "request_id": "req-retry-0001"}).json()
    b = env.client.post("/v1/runs", headers=h, json={"client_code": "QC-001", "request_id": "req-retry-0001"}).json()
    assert a["code"] == b["code"]
    assert len(env.client.get("/v1/runs", headers=h).json()["runs"]) == 1


def test_registering_a_code_made_elsewhere(env):
    h = signed(env)
    mk = lambda client, code: env.client.post("/v1/runs", headers=h, json={"client_code": client, "code": code})
    assert mk("QC-007", "QDOCK-260824-005").status_code == 200
    assert mk("QC-007", "QDOCK-260824-005").status_code == 200              # same again: fine, idempotent
    clash = mk("QC-009", "QDOCK-260824-005")
    assert clash.status_code == 409 and clash.json()["detail"]["code"] == "code_conflict"


def test_bad_inputs_are_rejected(env):
    h = signed(env)
    for body in ({"client_code": "ACME"}, {"client_code": "QC-1"}, {"client_code": "QC-001", "code": "RUN-1"},
                 {"client_code": "QC-001", "surprise": "field"}):
        assert env.client.post("/v1/runs", headers=h, json=body).status_code == 422


def test_runs_need_a_signed_in_full_session(env):
    assert env.client.post("/v1/runs", json={"client_code": "QC-001"}).status_code == 401
    temp = env.login("LEM").json()["access_token"]
    assert env.client.get("/v1/runs", headers=env.auth(temp)).status_code == 403


def ev(n, kind, data=None, utc="2026-11-07T21:30:00+00:00"):
    return {"id": UUID.format(n), "type": kind, "utc": utc, "data": data or {}}


def test_events_upload_is_idempotent_and_stamps_the_real_actor(env):
    h = signed(env, "JER")
    code = env.client.post("/v1/runs", headers=h, json={"client_code": "QC-001"}).json()["code"]
    batch = {"events": [ev(1, "run_created", {"package": "Hadron"}), ev(2, "receptor_prepared", {"method": "pdb2pqr", "ph": 7.4, "box": "blind"})]}
    first = env.client.post(f"/v1/runs/{code}/events", headers=h, json=batch).json()
    again = env.client.post(f"/v1/runs/{code}/events", headers=h, json=batch).json()
    assert first == {"accepted": 2, "duplicates": 0, "fields_dropped": 0} and again["accepted"] == 0 and again["duplicates"] == 2
    got = env.client.get(f"/v1/runs/{code}/events", headers=h).json()["events"]
    assert [e["actor"] for e in got] == ["JER", "JER"]


def test_chemistry_cannot_leave_the_laptop_through_events(env):
    h = signed(env)
    code = env.client.post("/v1/runs", headers=h, json={"client_code": "QC-001"}).json()["code"]
    sneaky = {"events": [
        ev(1, "ligand_renamed", {"from": "client-secret-compound", "to": "CC(=O)Nc1ccc(O)cc1"}),
        ev(2, "ligands_prepared", {"ligands": 3, "states": 4, "smiles": "CCO", "names": ["secret"]}),
        ev(3, "run_completed", {"run_id": "ABC123", "ligands": 3, "vina": "1.2.7", "best_affinity": -9.9, "sequence": "GWLLK"}),
    ]}
    r = env.client.post(f"/v1/runs/{code}/events", headers=h, json=sneaky).json()
    assert r["accepted"] == 3 and r["fields_dropped"] == 6
    stored = json.dumps(env.client.get(f"/v1/runs/{code}/events", headers=h).json())
    for secret in ("client-secret-compound", "CC(=O)Nc1ccc", "CCO", "secret", "-9.9", "GWLLK", "best_affinity", "smiles"):
        assert secret not in stored


def test_unknown_event_types_bad_times_and_unknown_runs_are_rejected(env):
    h = signed(env)
    code = env.client.post("/v1/runs", headers=h, json={"client_code": "QC-001"}).json()["code"]
    assert env.client.post(f"/v1/runs/{code}/events", headers=h, json={"events": [ev(1, "download_everything")]}).status_code == 422
    assert env.client.post(f"/v1/runs/{code}/events", headers=h, json={"events": [ev(1, "run_created", utc="yesterday-ish")]}).status_code == 422
    assert env.client.post("/v1/runs/QDOCK-000101-001/events", headers=h, json={"events": [ev(1, "run_created")]}).status_code == 404
    too_many = {"events": [ev(n, "ligand_renamed") for n in range(201)]}
    assert env.client.post(f"/v1/runs/{code}/events", headers=h, json=too_many).status_code == 422


def test_dashboard_summary_is_derived_from_events(env):
    h = signed(env)
    code = env.client.post("/v1/runs", headers=h, json={"client_code": "QC-004"}).json()["code"]
    row = lambda: env.client.get("/v1/runs?client=QC-004", headers=h).json()["runs"][0]
    assert row()["stage"] == "new"
    env.client.post(f"/v1/runs/{code}/events", headers=h, json={"events": [ev(1, "receptor_prepared", {"method": "pdb2pqr"})]})
    assert row()["stage"] == "receptor ready"
    env.client.post(f"/v1/runs/{code}/events", headers=h, json={"events": [
        ev(2, "ligands_prepared", {"ligands": 5, "states": 6}), ev(3, "run_completed", {"ligands": 5, "run_id": "R1"}),
        ev(4, "report_generated", {"final": False}), ev(5, "report_generated", {"final": True})]})
    r = row()
    assert r["stage"] == "docked" and r["ligands"] == 5 and r["reports"] == 2 and r["last_actor"] == "LEM"
    assert env.client.get("/v1/runs?client=QC-999", headers=h).json()["runs"] == []
