import math

from rdkit import Chem

from qrksdock.core import contacts


def _pdb_atom(serial, name, residue, residue_id, xyz, element):
    x, y, z = xyz
    return (f"ATOM  {serial:5d} {name:>4s} {residue:>3s} A{residue_id:4d}    "
            f"{x:8.3f}{y:8.3f}{z:8.3f}{1.0:6.2f}{0.0:6.2f}          {element:>2s}  ")


def _pdbqt_atom(serial, name, xyz, element):
    x, y, z = xyz
    return (f"ATOM  {serial:5d} {name:<4s} LIG A   1    "
            f"{x:8.3f}{y:8.3f}{z:8.3f}{1.0:6.2f}{0.0:6.2f}    0.000 {element:>2s}")


def _molecule(smiles, conformer_coords):
    mol = Chem.MolFromSmiles(smiles)
    assert mol is not None
    for coordinates in conformer_coords:
        conformer = Chem.Conformer(mol.GetNumAtoms())
        for index, xyz in enumerate(coordinates):
            conformer.SetAtomPosition(index, xyz)
        mol.AddConformer(conformer, assignId=True)
    return mol


def _assert_residue_anchors(report):
    structures = {structure.residue: structure.molecule for structure in report.residue_structures}
    for interaction in report.interactions:
        atom_names = {
            atom.GetPDBResidueInfo().GetName().strip()
            for atom in structures[interaction.residue].GetAtoms()
            if atom.GetPDBResidueInfo() is not None
        }
        assert interaction.receptor_atom in atom_names


def test_analyse_uses_selected_pose_and_reports_anchored_candidates(tmp_path):
    ligand_coords = [(0.0, 0.0, 0.0), (1.45, 0.0, 0.0), (2.95, 0.0, 0.0)]
    offset_coords = [(x + 20.0, y, z) for x, y, z in ligand_coords]
    mol = _molecule("[NH3+]CC", [offset_coords, ligand_coords])
    receptor = tmp_path / "receptor.pdb"
    receptor.write_text("\n".join([
        _pdb_atom(1, "OD1", "ASP", 1, (0.0, 2.7, 0.0), "O"),
        _pdb_atom(2, "CD1", "LEU", 2, (2.95, 2.0, 0.0), "C"),
    ]))
    pose = tmp_path / "poses.pdbqt"
    pose.write_text(
        "MODEL        1\n"
        + "\n".join(_pdbqt_atom(i + 1, f"C{i}", xyz, ("N" if i == 0 else "C"))
                    for i, xyz in enumerate(offset_coords))
        + "\nENDMDL\nMODEL        2\n"
        + "\n".join(_pdbqt_atom(i + 1, f"C{i}", xyz, ("N" if i == 0 else "C"))
                    for i, xyz in enumerate(ligand_coords))
        + "\nENDMDL\n"
    )

    report = contacts.analyse(receptor, pose, mol, pose_index=1)

    kinds = {interaction.kind for interaction in report.interactions}
    assert {"polar", "salt_bridge", "hydrophobic"} <= kinds
    assert {
        interaction.kind for interaction in report.interactions if interaction.residue == "LEU2A"
    } == {"hydrophobic"}
    assert all(0 <= interaction.ligand_atom < mol.GetNumAtoms() for interaction in report.interactions)
    _assert_residue_anchors(report)


def test_analyse_finds_aromatic_ring_candidates(tmp_path):
    ligand_coords = [
        (1.4 * math.cos(index * math.pi / 3), 1.4 * math.sin(index * math.pi / 3), 0.0)
        for index in range(6)
    ]
    mol = _molecule("c1ccccc1", [ligand_coords])
    ring_coords = {
        "CG": (1.4, 0.0),
        "CD1": (0.7, math.sqrt(3) * 0.7),
        "CE1": (-0.7, math.sqrt(3) * 0.7),
        "CZ": (-1.4, 0.0),
        "CE2": (-0.7, -math.sqrt(3) * 0.7),
        "CD2": (0.7, -math.sqrt(3) * 0.7),
    }
    ring_names = ("CG", "CD1", "CD2", "CE1", "CE2", "CZ")
    receptor = tmp_path / "receptor.pdb"
    receptor.write_text("\n".join(
        [
            *(
                _pdb_atom(index + 1, name, "PHE", 5, (*ring_coords[name], 4.5), "C")
                for index, name in enumerate(ring_names)
            ),
            _pdb_atom(7, "NH1", "ARG", 8, (0.0, 0.0, 0.0), "N"),
        ]
    ))
    pose = tmp_path / "pose.pdbqt"
    pose.write_text("\n".join(
        _pdbqt_atom(index + 1, f"C{index}", xyz, "C")
        for index, xyz in enumerate(ligand_coords)
    ))

    report = contacts.analyse(receptor, pose, mol)

    kinds = {interaction.kind for interaction in report.interactions}
    assert {"pi_stacking", "cation_pi"} <= kinds
    _assert_residue_anchors(report)
