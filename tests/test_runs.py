import json
from datetime import datetime

import pytest

from qrksdock.core import rules, runs
from qrksdock.core.runs import Run, RunError, list_runs, next_qdock_code, normalize_client_code, parse_qdock_code


@pytest.mark.parametrize("raw, expected", [("QC-001", "QC-001"), ("qc-7", "QC-007"), (" QC-12 ", "QC-012"),
                                           ("[QC-005]", "QC-005"), ("QC-0012", "QC-0012")])
def test_client_code_normalization(raw, expected):
    assert normalize_client_code(raw) == expected


@pytest.mark.parametrize("bad", ["C-001", "QC-", "QC-1234567", "ACME", "", "QC001"])
def test_bad_client_codes(bad):
    with pytest.raises(RunError):
        normalize_client_code(bad)


def test_qdock_serial_counts_across_all_clients_but_only_today(tmp_path):
    day = datetime(2026, 11, 2)
    assert next_qdock_code(tmp_path, day) == "QDOCK-261102-001"
    (tmp_path / "QC-001" / "QDOCK-261102-001").mkdir(parents=True)
    (tmp_path / "QC-002" / "QDOCK-261102-002").mkdir(parents=True)
    (tmp_path / "QC-001" / "QDOCK-261101-009").mkdir(parents=True)        # a different day must not count
    assert next_qdock_code(tmp_path, day) == "QDOCK-261102-003"
    assert parse_qdock_code("QDOCK-260824-001") == {"date": "260824", "serial": "001"}
    assert parse_qdock_code("QDOCK-26-1") is None


def test_create_makes_the_expected_layout(tmp_path):
    r = Run.create(tmp_path, "qc-1", "LEM", package="Hadron")
    assert r.client == "QC-001" and r.code.startswith("QDOCK-") and r.package == "Hadron"
    assert r.path == tmp_path / "QC-001" / r.code                          # client folder, then QDOCK folder, no brackets
    for sub in ("input", "work", "results", "reports", "logs"):
        assert (r.path / sub).is_dir()
    assert not (r.path / "events").exists()
    meta = json.loads((r.path / "run.json").read_text())
    assert meta["schema"] == 2 and meta["created_by"] == "LEM" and "status" not in meta
    assert [e["type"] for e in r.activity()] == ["run_created"]


def test_consecutive_runs_get_consecutive_codes(tmp_path):
    a = Run.create(tmp_path, "QC-001", "LEM")
    b = Run.create(tmp_path, "QC-002", "JML")
    assert int(b.code[-3:]) == int(a.code[-3:]) + 1


def test_duplicate_and_bad_inputs(tmp_path):
    a = Run.create(tmp_path, "QC-001", "LEM", qdock_code="QDOCK-260824-001")
    with pytest.raises(RunError, match="already exists"):
        Run.create(tmp_path, "QC-001", "LEM", qdock_code=a.code)
    with pytest.raises(RunError, match="QDOCK code"):
        Run.create(tmp_path, "QC-001", "LEM", qdock_code="RUN-1")
    with pytest.raises(RunError, match="package"):
        Run.create(tmp_path, "QC-001", "LEM", package="Gold")


def test_any_operator_can_create_and_nothing_is_locked(tmp_path):
    r = Run.create(tmp_path, "QC-009", "ERD")                              # Marketing Lead: identify only, no restrictions
    assert r.meta["created_by"] == "ERD"
    assert not hasattr(Run, "set_flag") and not hasattr(Run, "check_can_run") and not hasattr(Run, "report_state")


def test_ticket_module_is_gone():
    with pytest.raises(ImportError):
        __import__("qrksdock.core.tickets")
    assert "flags" not in rules.load() and "permissions" not in rules.load()


def test_open_adopts_a_folder_made_by_hand(tmp_path):
    hand = tmp_path / "QC-007" / "QDOCK-260824-001"
    hand.mkdir(parents=True)
    r = Run.open(hand, "JML")
    assert r.client == "QC-007" and r.code == "QDOCK-260824-001" and (hand / "run.json").exists()
    assert Run.open(hand).code == r.code                                    # opening again is plain
    with pytest.raises(RunError, match="not a QRKSDock run folder"):
        Run.open(tmp_path / "Random Folder")
    stray = tmp_path / "QDOCK-260824-002"
    stray.mkdir()
    with pytest.raises(RunError, match="client folder"):
        Run.open(stray)                                                      # a QDOCK folder outside a QC folder


def test_activity_log_survives_a_half_synced_line(tmp_path):
    r = Run.create(tmp_path, "QC-001", "LEM")
    with open(r.path / "logs" / "activity.jsonl", "a") as f:
        f.write('{"utc": "broken\n')
    r.log("LEM", "note", {"x": 1})
    assert [e["type"] for e in r.activity()] == ["run_created", "note"]


def test_package_limits_apply_only_when_a_package_is_chosen(tmp_path):
    free = Run.create(tmp_path, "QC-001", "LEM")
    assert free.check_limits(500, 500) == []
    capped = Run.create(tmp_path, "QC-002", "LEM", package="Hadron")
    assert capped.check_limits(5, 5) == [] and len(capped.check_limits(6, 6)) == 2


def test_list_runs_summarises_progress(tmp_path):
    a = Run.create(tmp_path, "QC-001", "LEM", qdock_code="QDOCK-260824-001")
    b = Run.create(tmp_path, "QC-002", "JML", qdock_code="QDOCK-260824-002")
    (b.path / "work" / "state.json").write_text(json.dumps(
        {"receptor": {}, "prepared": [1], "results": [{"ligand": "x", "best_affinity": -7.5}, {"ligand": "y", "best_affinity": -6.1}]}))
    (tmp_path / "Not a client").mkdir()
    rows = list_runs(tmp_path)
    assert [r["code"] for r in rows] == ["QDOCK-260824-002", "QDOCK-260824-001"]       # newest first
    assert rows[0]["stage"] == "docked" and rows[0]["ligands"] == 2 and rows[0]["best"] == -7.5
    assert rows[1]["stage"] == "new" and rows[1]["best"] is None
