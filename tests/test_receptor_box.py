import pytest

from qrksdock.core import box as B
from qrksdock.core import receptor as R


def test_inspect_raw_structure(data):
    s = R.inspect_pdb(data / "1IEP_receptorH.pdb")
    assert s.has_hydrogens and list(s.chains) == ["A"]
    clean = R.inspect_pdb(data / "1AFS_A_clean.pdb")
    assert clean.chains == {"A": 319} and not clean.has_hydrogens


def test_prepare_receptor_pdb2pqr(tmp_path, data):
    pr = R.prepare_receptor(data / "1AFS_A_clean.pdb", tmp_path, ph=7.4)
    assert pr.pdbqt.exists() and pr.protonated_pdb.exists()
    assert pr.residue_states.get("HIE", 0) + pr.residue_states.get("HID", 0) > 0     # histidine states assigned
    assert pr.chains_kept == ["A"]


def test_removes_waters_ligands_cofactors(tmp_path):
    pdb = tmp_path / "x.pdb"
    pdb.write_text(
        "ATOM      1  N   GLY A   1      11.104   6.134  -6.504  1.00  0.00           N\n"
        "ATOM      2  CA  GLY A   1      11.639   6.071  -5.147  1.00  0.00           C\n"
        "ATOM      3  C   GLY A   1      13.150   6.012  -5.162  1.00  0.00           C\n"
        "ATOM      4  O   GLY A   1      13.752   5.980  -4.095  1.00  0.00           O\n"
        "HETATM    5  O   HOH A 101      20.000  20.000  20.000  1.00  0.00           O\n"
        "HETATM    6  C1  NAP A 301      21.000  21.000  21.000  1.00  0.00           C\n")
    kept, removed = R._clean(pdb, tmp_path / "c.pdb", None, strip_h=True)
    assert kept == ["A"] and removed == {"HOH": 1, "NAP": 1}
    assert "NAP" not in (tmp_path / "c.pdb").read_text()


def test_as_is_requires_hydrogens(tmp_path, data):
    with pytest.raises(R.ReceptorError, match="no hydrogens"):
        R.prepare_receptor(data / "1AFS_A_clean.pdb", tmp_path, method="as_is")


def test_boxes(tmp_path, data):
    blind = B.box_blind(data / "1IEP_receptorH.pdb")
    assert blind.mode == "blind" and max(blind.size) > 40
    ref = B.box_from_reference((0, 0, 0), (3.5, 10, 3.4))
    assert min(ref.size) >= 20 and ref.size[1] == pytest.approx(26.0)
    assert B.recommended_exhaustiveness(ref) == 16
    assert B.recommended_exhaustiveness(blind) == 32
    assert B.box_warnings(B.box_manual((0, 0, 0), (80, 20, 20)))
    with pytest.raises(ValueError):
        B.box_manual((0, 0, 0), (0, 10, 10))


def test_box_vectors_require_three_coordinates():
    with pytest.raises(ValueError, match="exactly three coordinates"):
        B.box_manual((0, 0), (10, 10, 10))
    with pytest.raises(ValueError, match="exactly three coordinates"):
        B.box_manual((0, 0, 0), (10, 10))
