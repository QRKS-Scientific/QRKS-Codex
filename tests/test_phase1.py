"""v0.2.0: top-10 poses, raw Vina log, automatic seed, pKd, editable ligand names."""
import csv
import json
import shutil

import pytest

from qrksdock import paths
from qrksdock.core import thermo
from qrksdock.core import vina_runner as V
from qrksdock.core.pipeline import DockParams, PipelineError, Project
from qrksdock.core.tickets import Ticket

SMALL = "CC(C)Cc1ccc(cc1)C(C)C(=O)O  ibuprofen\nCCO ethanol\n"
PEPT = "GW dipeptide_GW\n"


@pytest.fixture(scope="module")
def run_dir(tmp_path_factory, vina_exe):
    root = tmp_path_factory.mktemp("p1")
    t = Ticket.create(root, "Hadron", "LEM", test=True)
    p = Project(t, "LEM")
    p.prepare_receptor(paths.asset("selftest", "mini_receptor.pdb"), box_mode="blind")
    p.prepare_ligands(SMALL, PEPT)
    p.run_docking(DockParams(exhaustiveness=4, cpu=1))          # defaults: 10 poses, energy range 10, automatic seed
    return t.path


@pytest.fixture()
def project(run_dir, tmp_path):
    dest = tmp_path / "copy"
    shutil.copytree(run_dir, dest)
    return Project(Ticket.open(dest), "LEM")


# ---- thermodynamics ---------------------------------------------------------------------------
def test_pkd_values():
    assert thermo.estimate_pkd(-9.0) == pytest.approx(6.60, abs=0.01)
    assert thermo.estimate_pkd(-12.86) == pytest.approx(9.43, abs=0.01)
    assert thermo.estimate_pkd(0.0) == 0.0
    assert thermo.estimate_pkd(-10) > thermo.estimate_pkd(-5) > 0
    assert thermo.format_kd(thermo.estimate_kd_molar(-9.0)).endswith("nM")


# ---- poses, seed, log -------------------------------------------------------------------------
def test_top_ten_poses_ranked(project):
    for r in project.results:
        assert 5 <= len(r.affinities) <= 10
        assert r.affinities == sorted(r.affinities)               # best (most negative) first
        assert len(r.rmsd_lb) == len(r.affinities)
    assert DockParams().num_modes == 10 and DockParams().seed is None


def test_vina_log_is_complete_and_raw(run_dir, project):
    log = (run_dir / "results" / "vina_output.log").read_text(encoding="utf-8")
    n = len(project.results)
    assert log.count("random seed") == n and log.count("mode |   affinity") == n
    assert log.count("# =====") == n and "AutoDock Vina v1.2" in log
    per_ligand = list((run_dir / "work" / "docking" / "logs").glob("*.log"))
    assert len(per_ligand) == n


def test_automatic_seed_is_recorded_and_reproduces(run_dir, project, vina_exe):
    r = project.best_per_ligand()[0]
    assert isinstance(r.seed, int)
    box = project.box
    again = V.run_vina(vina_exe, project._abs(project.s["receptor"]["pdbqt"]),
                       project._abs(next(p["pdbqt"] for p in project.s["prepared"] if p["state"] == r.state)),
                       box, run_dir.parent / "again.pdbqt", exhaustiveness=4, num_modes=10, energy_range=10, seed=r.seed, cpu=1)
    assert [p.affinity for p in again.poses] == r.affinities      # a negative seed is accepted too


def test_two_automatic_seeds_differ(vina_exe, project, tmp_path):
    seeds = set()
    for i in range(2):
        run = V.run_vina(vina_exe, project._abs(project.s["receptor"]["pdbqt"]), project._abs(project.s["prepared"][1]["pdbqt"]),
                         project.box, tmp_path / f"s{i}.pdbqt", exhaustiveness=1, num_modes=3, energy_range=3, cpu=1)
        seeds.add(run.seed)
    assert len(seeds) == 2 and None not in seeds


# ---- exports ---------------------------------------------------------------------------------------
def test_csv_exports(run_dir, project):
    rows = list(csv.DictReader(open(run_dir / "results" / "results.csv", encoding="utf-8")))
    assert len(rows) == 3 and "estimated_pKd" in rows[0] and "pose_10_kcal_per_mol" in rows[0] and "vina_seed" in rows[0]
    assert float(rows[0]["best_affinity_kcal_per_mol"]) <= float(rows[-1]["best_affinity_kcal_per_mol"])
    poses = list(csv.DictReader(open(run_dir / "results" / "poses.csv", encoding="utf-8")))
    assert len(poses) == sum(len(r.affinities) for r in project.results)


# ---- renaming --------------------------------------------------------------------------------------------
def test_rename_flows_to_every_output(project):
    run_id = json.loads((project.ticket.path / "results" / "manifest.json").read_text())["run_id"]
    assert project.rename_ligand("ibuprofen", "Ibuprofen racemic") == "Ibuprofen_racemic"     # spaces become underscores
    res = project.ticket.path / "results"
    names = [r["ligand"] for r in csv.DictReader(open(res / "results.csv", encoding="utf-8"))]
    assert "Ibuprofen_racemic" in names and "ibuprofen" not in names
    assert (res / "poses" / "Ibuprofen_racemic_poses.sdf").exists() and not (res / "poses" / "ibuprofen_poses.sdf").exists()
    assert "Ibuprofen_racemic" in (res / "vina_output.log").read_text(encoding="utf-8")
    man = json.loads((res / "manifest.json").read_text())
    assert man["run_id"] == run_id and man["display_names"] == {"ibuprofen": "Ibuprofen_racemic"}
    again = Project(Ticket.open(project.ticket.path), "LEM")                                      # survives reopening
    assert again.display_ligand("ibuprofen") == "Ibuprofen_racemic"


@pytest.mark.parametrize("bad, message", [("", "at least one"), ("!!!", "at least one"), ("ETHANOL", "already used")])
def test_rename_rejects_bad_names(project, bad, message):
    with pytest.raises(PipelineError, match=message):
        project.rename_ligand("dipeptide_GW", bad)


def test_rename_unknown_ligand(project):
    with pytest.raises(PipelineError, match="Unknown"):
        project.rename_ligand("nope", "x")


# ---- report ----------------------------------------------------------------------------------------------
def test_report_shows_pkd_new_names_and_pose_strip(project):
    pypdf = pytest.importorskip("pypdf")
    from qrksdock.core.report import generate_report
    project.rename_ligand("ethanol", "EtOH_control")
    text = "".join(pg.extract_text() for pg in pypdf.PdfReader(str(generate_report(project, "LEM"))).pages)
    assert "EtOH_control" in text and "Est. pKd" in text and "vina_output.log" in text and "kcal/mol" in text
    assert "random seed 42" not in text
