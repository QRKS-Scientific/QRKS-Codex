import pytest

from qrksdock.core import ligands as L

KYN = "C1=CC=C(C(=C1)C(=O)C[C@@H](C(=O)O)N)N"


def test_parse_smiles_and_names():
    ins = L.parse_smiles_text("smiles,name\n# comment\nCCO ethanol\nCC(=O)O,acetic acid\nCCN\n")
    assert [i.name for i in ins] == ["ethanol", "acetic_acid", "ligand_03"]


def test_stereo_gate_policies():
    ins = L.parse_smiles_text(f"{KYN} defined\nCC(C)Cc1ccc(cc1)C(C)C(=O)O undefined")
    warn = L.check_ligands(ins, "warn")
    assert all(c.ok for c in warn) and warn[1].unspecified_centers == 1 and warn[1].warnings
    block = L.check_ligands(ins, "block")
    assert block[0].ok and not block[1].ok


def test_duplicates_and_bad_smiles():
    ins = L.parse_smiles_text("CCO a\nCCN a\nnot_a_smiles b")
    c = L.check_ligands(ins)
    assert c[0].ok and not c[1].ok and not c[2].ok


def test_peptide_rules():
    c = L.check_ligands(L.parse_peptide_text("GW\nLLPK\nA\nACDEFGH\nAXG"))
    assert [x.ok for x in c] == [True, True, False, False, False]
    assert "2-6" in c[2].errors[0]
    assert "Unsupported" in c[4].errors[0]


def test_peptide_counts_as_one_ligand_each():
    assert len(L.parse_peptide_text("GW first\nLLPK second")) == 2


def test_prepare_small_molecule_and_peptide(tmp_path):
    kyn = L.prepare_ligand(L.parse_smiles_text(f"{KYN} kyn")[0], tmp_path, 7.4, 42)
    assert len(kyn) >= 1 and kyn[0].pdbqt.exists() and "TORSDOF" in kyn[0].pdbqt.read_text()
    ibu = L.prepare_ligand(L.parse_smiles_text("CC(C)Cc1ccc(cc1)C(C)C(=O)O ibu")[0], tmp_path, 7.4, 42)
    assert ibu[0].charge == -1                          # carboxylic acid deprotonated at pH 7.4
    pep = L.prepare_ligand(L.parse_peptide_text("LLPK tetra")[0], tmp_path, 7.4, 42)
    assert pep[0].charge == 1 and pep[0].kind == "peptide"


def test_preparation_is_deterministic(tmp_path):
    a = L.prepare_ligand(L.parse_smiles_text(f"{KYN} k")[0], tmp_path / "a", 7.4, 42)[0].pdbqt.read_text()
    b = L.prepare_ligand(L.parse_smiles_text(f"{KYN} k")[0], tmp_path / "b", 7.4, 42)[0].pdbqt.read_text()
    assert a == b


def test_reference_ligand_requires_3d(tmp_path):
    from rdkit import Chem
    from rdkit.Chem import AllChem
    m = Chem.MolFromSmiles("CCO")
    AllChem.Compute2DCoords(m)
    w = Chem.SDWriter(str(tmp_path / "flat.sdf"))
    w.write(m)
    w.close()
    with pytest.raises(L.LigandError, match="3D"):
        L.prepare_reference_ligand(tmp_path / "flat.sdf", tmp_path / "out")
