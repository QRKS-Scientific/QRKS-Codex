import json

import pytest

from qrksdock import paths
from qrksdock.core.pipeline import DockParams, PipelineError, Project
from qrksdock.core.report import generate_report
from qrksdock.core.tickets import PermissionDenied, Ticket

SMALL = "C1=CC=C(C(=C1)C(=O)C[C@@H](C(=O)O)N)N L-kynurenine\nCCO ethanol\n"
PEPT = "GW dipeptide_GW\n"
FAST = DockParams(exhaustiveness=2, num_modes=3, cpu=1)


@pytest.fixture(scope="module")
def finished(tmp_path_factory, vina_exe):
    root = tmp_path_factory.mktemp("tickets")
    t = Ticket.create(root, "Hadron", "LEM", test=True)
    p = Project(t, "LEM")
    p.prepare_receptor(paths.asset("selftest", "mini_receptor.pdb"), box_mode="blind")
    p.prepare_ligands(SMALL, PEPT)
    p.run_docking(FAST)
    return t, p


def test_results_and_outputs(finished):
    t, p = finished
    best = p.best_per_ligand()
    assert len(best) == 3 and best[0].best_affinity <= best[-1].best_affinity
    assert (t.path / "results" / "results.csv").exists()
    assert list((t.path / "results" / "poses").glob("*.sdf"))
    man = json.loads((t.path / "results" / "manifest.json").read_text())
    assert len(man["run_id"]) == 16 and man["parameters"]["seed"] == 42
    assert man["environment"]["autodock_vina"].startswith("1.2")
    assert all(len(h) == 64 for h in man["file_sha256"].values())


def test_state_persists_across_reopen(finished):
    t, _ = finished
    again = Project(Ticket.open(t.path), "LEM")
    assert again.receptor_ready and again.ligands_ready and len(again.results) == 3 and again.box is not None


def test_report_is_watermarked_on_test_ticket(finished):
    _, p = finished
    pdf = generate_report(p, "LEM")
    assert pdf.name.endswith("_TEST.pdf") and pdf.stat().st_size > 20_000


def test_tier_limit_blocks_preparation(tmp_path):
    t = Ticket.create(tmp_path, "Hadron", "LEM", test=True)
    p = Project(t, "LEM")
    too_many = "\n".join(f"C{'C' * i} l{i}" for i in range(1, 8))
    with pytest.raises(PipelineError, match="limit"):
        p.prepare_ligands(too_many, "")


def test_real_ticket_blocks_docking_until_paid_and_seal_logic(tmp_path, vina_exe):
    t = Ticket.create(tmp_path, "Hadron", "JML")
    p = Project(t, "LEM")
    p.prepare_receptor(paths.asset("selftest", "mini_receptor.pdb"), box_mode="blind")
    p.prepare_ligands("CCO ethanol\n", "")
    with pytest.raises(PermissionDenied, match="ACTIVATED & PAID"):
        p.run_docking(FAST)
    t.set_flag("JCG", "activated_paid")
    p.run_docking(FAST)
    pdf = generate_report(p, "LEM")
    assert pdf.name.endswith("_PREVIEW.pdf")                         # balance not cleared: watermarked
    t.set_flag("JER", "qa_passed")
    t.set_flag("LEM", "report_signed")
    t.set_flag("JCG", "balance_cleared")
    final = generate_report(p, "LEM")
    assert final.name == f"{t.id}_QRKSDock_Technical_Report.pdf"      # clean name: no watermark
    with pytest.raises(PermissionDenied):
        generate_report(Project(t, "ERD"), "ERD")                    # Marketing cannot issue reports


def test_cancel_stops_docking(tmp_path, vina_exe):
    import threading
    from qrksdock.core.pipeline import Cancelled
    t = Ticket.create(tmp_path, "Hadron", "LEM", test=True)
    p = Project(t, "LEM")
    p.prepare_receptor(paths.asset("selftest", "mini_receptor.pdb"), box_mode="blind")
    p.prepare_ligands("CCO ethanol\nCCN ethylamine\n", "")
    ev = threading.Event()
    ev.set()
    with pytest.raises(Cancelled):
        p.run_docking(FAST, cancel=ev)
