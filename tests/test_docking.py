import sys

import pytest
from rdkit import Chem

from qrksdock.core import box as B
from qrksdock.core import ligands as L
from qrksdock.core import receptor as R
from qrksdock.core import validation as VAL
from qrksdock.core import vina_runner as V
from conftest import slow


def test_vina_version(vina_exe):
    assert V.vina_version(vina_exe).startswith("1.2")


@pytest.mark.skipif(sys.platform == "win32", reason="uses a shell-script stand-in")
def test_vina_missing_or_wrong_binary(tmp_path):
    fake = tmp_path / "vina"
    fake.write_text("#!/bin/sh\necho hello\n")
    fake.chmod(0o755)
    with pytest.raises(V.VinaError, match="does not look like"):
        V.vina_version(fake)


def test_crystal_pose_has_zero_rmsd(tmp_path, data):
    ref = L.prepare_reference_ligand(data / "1AFS_TES.sdf", tmp_path)
    assert VAL.rmsd_per_pose(ref.pdbqt, ref.mol) == pytest.approx([0.0], abs=1e-3)


def test_same_seed_gives_identical_results(tmp_path, data, vina_exe):
    pr = R.prepare_receptor(data / "1AFS_A_clean.pdb", tmp_path / "rec")
    ref = L.prepare_reference_ligand(data / "1AFS_TES.sdf", tmp_path / "ref")
    box = B.box_from_reference(ref.centroid, ref.extent)
    kw = dict(exhaustiveness=4, num_modes=5, energy_range=3, seed=7, cpu=1)
    a = V.run_vina(vina_exe, pr.pdbqt, ref.pdbqt, box, tmp_path / "a.pdbqt", **kw)
    b = V.run_vina(vina_exe, pr.pdbqt, ref.pdbqt, box, tmp_path / "b.pdbqt", **kw)
    assert [p.affinity for p in a.poses] == [p.affinity for p in b.poses]


def test_cofactor_dependent_redocking_is_flagged(tmp_path, data, vina_exe):
    """1AFS testosterone binds beside NADP. With the cofactor removed the pocket changes, and the
    validation gate must say so rather than silently reporting a good-looking score."""
    pr = R.prepare_receptor(data / "1AFS_A_clean.pdb", tmp_path / "rec")
    ref = L.prepare_reference_ligand(data / "1AFS_TES.sdf", tmp_path / "ref")
    box = B.box_from_reference(ref.centroid, ref.extent)
    run = V.run_vina(vina_exe, pr.pdbqt, ref.pdbqt, box, tmp_path / "o.pdbqt", exhaustiveness=8, num_modes=9,
                     energy_range=3, seed=42, cpu=1)
    val = VAL.evaluate(run.out_pdbqt, ref.mol, [p.affinity for p in run.poses])
    assert val.passed is False and val.rmsd_top > val.threshold


@slow
def test_imatinib_abl_redocking_passes(tmp_path, data, vina_exe):
    """Classic benchmark (PDB 1IEP). The whole pipeline must reproduce the crystal pose."""
    pr = R.prepare_receptor(data / "1IEP_receptorH.pdb", tmp_path / "rec")
    ref = L.prepare_reference_ligand(data / "1IEP_ligand_STI.sdf", tmp_path / "ref")
    box = B.box_from_reference(ref.centroid, ref.extent)
    run = V.run_vina(vina_exe, pr.pdbqt, ref.pdbqt, box, tmp_path / "o.pdbqt", exhaustiveness=8, num_modes=9,
                     energy_range=3, seed=42, cpu=2)
    val = VAL.evaluate(run.out_pdbqt, ref.mol, [p.affinity for p in run.poses])
    assert val.passed, val.text()
    assert val.rmsd_top < 1.5
