import json

import pytest

from qrksdock import paths
from qrksdock.core.pipeline import DockParams, PipelineError, Project
from qrksdock.core.report import generate_report
from qrksdock.core.runs import Run

SMALL = "C1=CC=C(C(=C1)C(=O)C[C@@H](C(=O)O)N)N L-kynurenine\nCCO ethanol\n"
PEPT = "GW dipeptide_GW\n"
FAST = DockParams(exhaustiveness=2, num_modes=3, cpu=1)


@pytest.fixture(scope="module")
def finished(tmp_path_factory, vina_exe):
    root = tmp_path_factory.mktemp("runs")
    run = Run.create(root, "QC-001", "LEM")
    p = Project(run, "LEM")
    p.prepare_receptor(paths.asset("selftest", "mini_receptor.pdb"), box_mode="blind")
    p.prepare_ligands(SMALL, PEPT)
    p.run_docking(FAST)
    return run, p


def test_results_and_outputs(finished):
    run, p = finished
    best = p.best_per_ligand()
    assert len(best) == 3 and best[0].best_affinity <= best[-1].best_affinity
    assert (run.path / "results" / "results.csv").exists()
    assert list((run.path / "results" / "poses").glob("*.sdf"))
    man = json.loads((run.path / "results" / "manifest.json").read_text())
    assert len(man["run_id"]) == 16 and man["parameters"]["seed"] is None
    assert man["qdock_code"] == run.code and man["client_code"] == "QC-001" and "ticket_id" not in man
    assert set(man["vina_seeds"]) == {"L-kynurenine", "ethanol", "dipeptide_GW"}
    assert all(len(h) == 64 for h in man["file_sha256"].values())


def test_state_persists_across_reopen(finished):
    run, _ = finished
    again = Project(Run.open(run.path), "LEM")
    assert again.receptor_ready and again.ligands_ready and len(again.results) == 3 and again.box is not None


def test_any_operator_can_dock_and_nothing_blocks(tmp_path, vina_exe):
    """No payment gate, no role gate: the Marketing Lead can run a job on a brand new run."""
    run = Run.create(tmp_path, "QC-002", "ERD")
    p = Project(run, "ERD")
    p.prepare_receptor(paths.asset("selftest", "mini_receptor.pdb"), box_mode="blind")
    p.prepare_ligands("CCO ethanol\n", "")
    assert len(p.run_docking(FAST)) == 1
    assert [e["type"] for e in run.activity()][-2:] == ["ligands_prepared", "run_completed"]


def test_draft_and_final_reports(finished):
    pypdf = pytest.importorskip("pypdf")
    _, p = finished

    def text(path):
        return "".join(pg.extract_text() for pg in pypdf.PdfReader(str(path)).pages)

    draft = generate_report(p, "LEM")
    final = generate_report(p, "LEM", final=True)
    assert draft.name.endswith("_Technical_Report_DRAFT.pdf") and final.name.endswith("_Technical_Report_FINAL.pdf")
    td, tf = text(draft), text(final)
    assert "Draft (watermarked)" in td and "Final" in tf and "Draft (watermarked)" not in tf
    for t in (td, tf):
        assert "QC-001" in t and p.run.code in t
        assert "Lars E. Medice, RCh." in t                                    # the report names the lead with the credential
        assert "Integrity Seal" not in t and "Sign-off" not in t and "Ticket" not in t


def test_package_limit_blocks_preparation_only_when_chosen(tmp_path):
    p = Project(Run.create(tmp_path, "QC-003", "LEM", package="Hadron"), "LEM")
    too_many = "\n".join(f"C{'C' * i} l{i}" for i in range(1, 8))
    with pytest.raises(PipelineError, match="limit"):
        p.prepare_ligands(too_many, "")
    free = Project(Run.create(tmp_path, "QC-004", "LEM"), "LEM")
    assert len(free.prepare_ligands(too_many, "")) == 7                   # no package, no limit


def test_cancel_stops_docking(tmp_path, vina_exe):
    import threading
    from qrksdock.core.pipeline import Cancelled
    p = Project(Run.create(tmp_path, "QC-005", "LEM"), "LEM")
    p.prepare_receptor(paths.asset("selftest", "mini_receptor.pdb"), box_mode="blind")
    p.prepare_ligands("CCO ethanol\nCCN ethylamine\n", "")
    ev = threading.Event()
    ev.set()
    with pytest.raises(Cancelled):
        p.run_docking(FAST, cancel=ev)
