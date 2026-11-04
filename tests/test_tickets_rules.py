from datetime import datetime

import pytest

from qrksdock.core import rules
from qrksdock.core.tickets import PermissionDenied, Ticket, TicketError, next_ticket_id, parse_ticket_id


def test_tiers_match_portfolio():
    assert rules.tier_limits("Hadron")["small_molecules"] == 5
    assert rules.tier_limits("Fermion")["peptides"] == 10
    assert rules.tier_limits("Boson")["ppi_pairs"] == 5


def test_ticket_id_serials_and_brackets(tmp_path):
    day = datetime(2026, 11, 2)
    assert next_ticket_id(tmp_path, today=day) == "QDOCK-261102-001"
    (tmp_path / "[QDOCK-261102-001]").mkdir()
    (tmp_path / "[QDOCK-261102-002]").mkdir()
    (tmp_path / "[QDOCK-261101-009]").mkdir()          # other day, must not count
    assert next_ticket_id(tmp_path, today=day) == "QDOCK-261102-003"
    assert parse_ticket_id("[QDOCK-261102-003]")["serial"] == "003"
    assert parse_ticket_id("random folder") is None


def test_create_open_and_duplicate(tmp_path):
    t = Ticket.create(tmp_path, "Hadron", "LEM")
    assert t.path.name == f"[{t.id}]" and (t.path / "events").is_dir()
    again = Ticket.open(t.path)
    assert again.id == t.id and again.tier == "Hadron"
    with pytest.raises(TicketError):
        Ticket.create(tmp_path, "Hadron", "LEM", ticket_id=t.id)
    with pytest.raises(TicketError):
        Ticket.create(tmp_path, "Gold", "LEM")


def test_only_permitted_roles_create_tickets(tmp_path):
    with pytest.raises(PermissionDenied):
        Ticket.create(tmp_path, "Hadron", "ERD")       # Marketing Lead cannot create tickets


def test_payment_gate_and_flag_permissions(tmp_path):
    t = Ticket.create(tmp_path, "Fermion", "JML")
    with pytest.raises(PermissionDenied, match="ACTIVATED & PAID"):
        t.check_can_run("LEM")                         # not paid yet
    with pytest.raises(PermissionDenied):
        t.set_flag("LEM", "activated_paid")            # only Finance can verify payment
    t.set_flag("JCG", "activated_paid")
    t.check_can_run("LEM")                             # now allowed
    with pytest.raises(PermissionDenied, match="cannot run docking"):
        t.check_can_run("LPA")                         # Sales cannot run docking even when paid
    t.set_flag("JCG", "activated_paid", False)         # undo is logged, not erased
    assert t.flags()["activated_paid"] is False
    assert sum(1 for e in t.events() if e["type"] == "flag_set") == 2


def test_test_tickets_bypass_gates(tmp_path):
    t = Ticket.create(tmp_path, "Hadron", "ERD", test=True)
    t.check_can_run("ERD")
    t.set_flag("ERD", "qa_passed")
    assert t.report_state()["seal"] is False           # seal is never allowed on a test ticket
    assert t.report_state()["watermark"] is True


def test_seal_and_watermark_rules(tmp_path):
    t = Ticket.create(tmp_path, "Hadron", "LEM")
    s = t.report_state()
    assert s["seal"] is False and s["watermark"] is True
    t.set_flag("JER", "qa_passed")
    assert t.report_state()["seal"] is False           # QA alone is not enough
    t.set_flag("LEM", "report_signed")
    assert t.report_state()["seal"] is True and t.report_state()["watermark"] is True
    t.set_flag("JCG", "balance_cleared")
    assert t.report_state()["watermark"] is False


def test_tier_limits_enforced(tmp_path):
    t = Ticket.create(tmp_path, "Hadron", "LEM")
    assert t.check_limits(5, 5) == []
    assert len(t.check_limits(6, 6)) == 2


def test_events_survive_partial_sync(tmp_path):
    t = Ticket.create(tmp_path, "Hadron", "LEM")
    (t.path / "events" / "broken.json").write_text("{not json")     # a half-synced Drive file
    assert t.flags()["qa_passed"] is False
