"""Geometry-based interaction candidates for a selected docked pose.

The report includes close contacts, N/O polar pairs, hydrophobic contacts, charged pairs,
and aromatic/cation-pi candidates. These distance-based rules are not a full interaction
profiler and do not validate hydrogen-bond directionality or solvation.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from math import acos, degrees
from pathlib import Path

import numpy as np
from rdkit import Chem

from qrksdock.core import rules

_AD_ELEMENT = {"A": "C", "C": "C", "N": "N", "NA": "N", "NS": "N", "OA": "O", "OS": "O", "O": "O",
               "S": "S", "SA": "S", "P": "P", "F": "F", "CL": "CL", "BR": "BR", "I": "I",
               "HD": "H", "H": "H", "HS": "H"}
_HYDROPHOBIC_RESIDUES = {"ALA", "ILE", "LEU", "MET", "PHE", "PRO", "TRP", "VAL"}
_PI_STACKING_CUTOFF = 5.5
_CATION_PI_CUTOFF = 6.0
_PI_PARALLEL_ANGLE = 30.0
_PI_EDGE_ON_ANGLE = 60.0
_AROMATIC_RING_ATOMS = {
    "PHE": (("CG", "CD1", "CD2", "CE1", "CE2", "CZ"),),
    "TYR": (("CG", "CD1", "CD2", "CE1", "CE2", "CZ"),),
    "TRP": (("CG", "CD1", "CD2", "NE1", "CE2"), ("CD2", "CE2", "CZ2", "CH2", "CZ3", "CE3")),
    "HIS": (("CG", "ND1", "CD2", "CE1", "NE2"),),
    "HID": (("CG", "ND1", "CD2", "CE1", "NE2"),),
    "HIE": (("CG", "ND1", "CD2", "CE1", "NE2"),),
    "HIP": (("CG", "ND1", "CD2", "CE1", "NE2"),),
}


@dataclass
class ContactReport:
    residues: list[str] = field(default_factory=list)          # e.g. "TYR50"
    polar: list[tuple[str, str, float]] = field(default_factory=list)   # (ligand atom, residue atom, distance)
    interactions: list["DiagramInteraction"] = field(default_factory=list)
    residue_structures: list["ResidueStructure"] = field(default_factory=list)
    thresholds: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class DiagramInteraction:
    kind: str
    residue: str
    ligand_atom: int
    receptor_atom: str
    distance: float


@dataclass
class ResidueStructure:
    residue: str
    molecule: Chem.Mol


def _residue_id_from_line(line: str) -> str:
    return f"{line[22:26].strip()}{line[26].strip()}{line[21].strip()}"


def read_receptor_atoms(pdb: Path) -> list[tuple[str, str, str, np.ndarray, str]]:
    atoms = []
    for line in Path(pdb).read_text(errors="replace").splitlines():
        if not line.startswith("ATOM  "):
            continue
        el = (line[76:78].strip() or line[12:16].strip().lstrip("0123456789")[:1]).upper()
        if el == "H":
            continue
        atoms.append((line[17:20].strip(), _residue_id_from_line(line), line[12:16].strip(),
                      np.array([float(line[30:38]), float(line[38:46]), float(line[46:54])]), el))
    return atoms


def first_pose_atoms(out_pdbqt: Path, pose_index: int = 0) -> list[tuple[str, np.ndarray, str]]:
    if pose_index < 0:
        raise ValueError("Pose index must be non-negative.")
    atoms = []
    model_index = -1
    in_target_model = pose_index == 0
    for line in Path(out_pdbqt).read_text(errors="replace").splitlines():
        if line.startswith("MODEL"):
            model_index += 1
            in_target_model = model_index == pose_index
            continue
        if line.startswith("ENDMDL"):
            if in_target_model:
                break
            in_target_model = False
            continue
        if not in_target_model:
            continue
        if not line.startswith(("ATOM", "HETATM")):
            continue
        ad = line[77:79].strip().upper()
        el = _AD_ELEMENT.get(ad, ad[:1])
        if el == "H":
            continue
        atoms.append((line[12:16].strip(), np.array([float(line[30:38]), float(line[38:46]), float(line[46:54])]), el))
    return atoms


def _protein_charge(resname: str, atom_name: str) -> int:
    if resname in {"ASP", "GLU"} and atom_name in {"OD1", "OD2", "OE1", "OE2"}:
        return -1
    if resname == "ARG" and atom_name in {"NE", "NH1", "NH2"}:
        return 1
    if resname == "LYS" and atom_name == "NZ":
        return 1
    if resname == "HIP" and atom_name in {"ND1", "NE2"}:
        return 1
    return 0


def _ring_geometry(coords: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    center = coords.mean(axis=0)
    _, _, axes = np.linalg.svd(coords - center, full_matrices=False)
    return center, axes[-1]


def _residue_structures(receptor_pdb: Path, residue_names: set[str]) -> list[ResidueStructure]:
    receptor = Chem.MolFromPDBFile(str(receptor_pdb), removeHs=True)
    if receptor is None:
        raise ValueError(f"Could not read receptor residue structures from {receptor_pdb}.")

    atoms_by_residue: dict[str, list[int]] = {}
    for atom in receptor.GetAtoms():
        info = atom.GetPDBResidueInfo()
        if info is None or info.GetIsHeteroAtom():
            continue
        residue = (
            f"{info.GetResidueName().strip()}"
            f"{info.GetResidueNumber()}{info.GetInsertionCode().strip()}{info.GetChainId().strip()}"
        )
        if residue in residue_names:
            atoms_by_residue.setdefault(residue, []).append(atom.GetIdx())

    structures = []
    for residue in sorted(residue_names):
        source_indices = atoms_by_residue.get(residue)
        if not source_indices:
            raise ValueError(f"Could not find receptor structure for residue {residue}.")
        rw_mol = Chem.RWMol()
        mapped_indices: dict[int, int] = {}
        for source_index in source_indices:
            mapped_indices[source_index] = rw_mol.AddAtom(Chem.Atom(receptor.GetAtomWithIdx(source_index)))
        for bond in receptor.GetBonds():
            begin = bond.GetBeginAtomIdx()
            end = bond.GetEndAtomIdx()
            if begin in mapped_indices and end in mapped_indices:
                rw_mol.AddBond(mapped_indices[begin], mapped_indices[end], bond.GetBondType())
        fragment = rw_mol.GetMol()
        Chem.SanitizeMol(fragment)
        Chem.Kekulize(fragment, clearAromaticFlags=True)
        structures.append(ResidueStructure(residue, fragment))
    return structures


def analyse(receptor_pdb: Path, pose_pdbqt: Path, ligand_mol: Chem.Mol | None = None,
            pose_index: int = 0) -> ContactReport:
    if pose_index < 0:
        raise ValueError("Pose index must be non-negative.")
    cfg = rules.docking_defaults()
    cut, polar_cut = cfg["contact_cutoff_angstrom"], cfg["polar_contact_cutoff_angstrom"]
    thresholds = {
        "contact": float(cut),
        "polar": float(polar_cut),
        "pi_stacking": _PI_STACKING_CUTOFF,
        "cation_pi": _CATION_PI_CUTOFF,
        "pi_parallel_angle": _PI_PARALLEL_ANGLE,
        "pi_edge_on_angle": _PI_EDGE_ON_ANGLE,
    }
    rec = read_receptor_atoms(receptor_pdb)
    lig = first_pose_atoms(pose_pdbqt, pose_index)
    if not rec:
        raise ValueError("Receptor contains no heavy atoms.")
    if not lig:
        raise ValueError(f"Pose {pose_index + 1} contains no heavy atoms.")
    rxyz = np.array([a[3] for a in rec])
    lxyz = np.array([a[1] for a in lig])
    d = np.linalg.norm(rxyz[:, None, :] - lxyz[None, :, :], axis=2)
    ligand_indices: list[int] | None = None
    heavy_mol: Chem.Mol | None = None
    ligand_xyz: np.ndarray | None = None
    if ligand_mol is not None:
        heavy_mol = Chem.RemoveHs(ligand_mol)
        if pose_index >= heavy_mol.GetNumConformers():
            raise ValueError(f"Ligand pose {pose_index + 1} has no coordinates.")
        conformer = heavy_mol.GetConformer(pose_index)
        ligand_xyz = np.array([
            [conformer.GetAtomPosition(i).x, conformer.GetAtomPosition(i).y, conformer.GetAtomPosition(i).z]
            for i in range(heavy_mol.GetNumAtoms())
        ])
        ligand_indices = []
        used_indices: set[int] = set()
        for _, xyz, element in lig:
            candidates = [
                i for i in range(heavy_mol.GetNumAtoms())
                if i not in used_indices and heavy_mol.GetAtomWithIdx(i).GetSymbol().upper() == element.upper()
            ]
            if not candidates:
                raise ValueError("Could not match a docked atom to the ligand structure.")
            atom_index = min(candidates, key=lambda i: float(np.linalg.norm(ligand_xyz[i] - xyz)))
            if float(np.linalg.norm(ligand_xyz[atom_index] - xyz)) > 0.1:
                raise ValueError("Could not match docked atom coordinates to the ligand structure.")
            ligand_indices.append(atom_index)
            used_indices.add(atom_index)
        if len(used_indices) != heavy_mol.GetNumAtoms():
            raise ValueError("Docked pose does not contain every ligand heavy atom.")

    res_hit: dict[str, int] = {}
    for i in np.where((d <= cut).any(axis=1))[0]:
        name, num = rec[i][0], rec[i][1]
        res_hit.setdefault(f"{name}{num}", int(num.rstrip("ABCDEFGHIJKLMNOPQRSTUVWXYZ") or 0))
    residues = sorted(res_hit, key=lambda k: res_hit[k])
    polar = []
    interaction_distances: dict[tuple[str, str, int, str], float] = {}

    def add_interaction(kind: str, residue: str, ligand_atom: int, receptor_atom: str, distance: float) -> None:
        key = (kind, residue, ligand_atom, receptor_atom)
        interaction_distances[key] = min(distance, interaction_distances.get(key, float("inf")))

    residue_best: dict[str, tuple[float, int, str]] = {}
    for i, (rname, rnum, ratom, _, _) in enumerate(rec):
        residue = f"{rname}{rnum}"
        for j in np.where(d[i] <= cut)[0]:
            ligand_atom = ligand_indices[j] if ligand_indices is not None else -1
            if ligand_atom < 0:
                continue
            distance = float(d[i, j])
            if residue not in residue_best or distance < residue_best[residue][0]:
                residue_best[residue] = distance, ligand_atom, ratom

    if ligand_indices is not None and heavy_mol is not None and ligand_xyz is not None:
        for residue, (distance, ligand_atom, receptor_atom) in residue_best.items():
            add_interaction("contact", residue, ligand_atom, receptor_atom, distance)

    for j, (lname, _, lel) in enumerate(lig):
        if lel not in ("N", "O"):
            continue
        for i, (rname, rnum, ratom, _, rel) in enumerate(rec):
            if rel in ("N", "O") and d[i, j] <= polar_cut:
                distance = float(d[i, j])
                polar.append((lname, f"{rname}{rnum}:{ratom}", distance))
                if ligand_indices is not None:
                    add_interaction("polar", f"{rname}{rnum}", ligand_indices[j], ratom, distance)
    polar.sort(key=lambda t: t[2])

    if ligand_indices is not None and heavy_mol is not None and ligand_xyz is not None:
        hydrophobic_ligand_atoms = {
            atom.GetIdx() for atom in heavy_mol.GetAtoms()
            if atom.GetSymbol() == "C" and all(neighbor.GetSymbol() in {"C", "S"} for neighbor in atom.GetNeighbors())
        }
        for i, (rname, rnum, ratom, _, rel) in enumerate(rec):
            if rel != "C" or rname not in _HYDROPHOBIC_RESIDUES or ratom in {"N", "CA", "C", "O"}:
                continue
            for j in np.where(d[i] <= cut)[0]:
                ligand_atom = ligand_indices[j]
                if ligand_atom in hydrophobic_ligand_atoms:
                    add_interaction("hydrophobic", f"{rname}{rnum}", ligand_atom, ratom, float(d[i, j]))

        protein_charges = [
            (i, _protein_charge(rname, ratom))
            for i, (rname, _, ratom, _, _) in enumerate(rec)
            if _protein_charge(rname, ratom)
        ]
        ligand_charges = [
            (atom.GetIdx(), atom.GetFormalCharge())
            for atom in heavy_mol.GetAtoms()
            if atom.GetFormalCharge()
        ]
        for rec_index, protein_charge in protein_charges:
            rname, rnum = rec[rec_index][:2]
            for atom_index, ligand_charge in ligand_charges:
                if protein_charge * ligand_charge < 0:
                    atom_xyz = ligand_xyz[atom_index]
                    distance = float(np.linalg.norm(rec[rec_index][3] - atom_xyz))
                    if distance <= cut:
                        add_interaction("salt_bridge", f"{rname}{rnum}", atom_index, rec[rec_index][2], distance)

        ligand_rings = [
            ring for ring in heavy_mol.GetRingInfo().AtomRings()
            if len(ring) >= 5 and all(heavy_mol.GetAtomWithIdx(i).GetIsAromatic() for i in ring)
        ]
        receptor_residue_atoms: dict[tuple[str, str], dict[str, int]] = {}
        for i, (rname, rnum, ratom, _, _) in enumerate(rec):
            receptor_residue_atoms.setdefault((rname, rnum), {})[ratom] = i

        for (rname, rnum), atoms_by_name in receptor_residue_atoms.items():
            ring_specs = _AROMATIC_RING_ATOMS.get(rname)
            if not ring_specs:
                continue
            residue = f"{rname}{rnum}"
            for atom_names in ring_specs:
                if not all(name in atoms_by_name for name in atom_names):
                    continue
                ring_rec_indices = [atoms_by_name[name] for name in atom_names]
                rec_ring_xyz = np.array([rec[i][3] for i in ring_rec_indices])
                rec_center, rec_normal = _ring_geometry(rec_ring_xyz)

                for ring in ligand_rings:
                    lig_ring_xyz = ligand_xyz[list(ring)]
                    lig_center, lig_normal = _ring_geometry(lig_ring_xyz)
                    center_distance = float(np.linalg.norm(lig_center - rec_center))
                    normal_angle = degrees(acos(min(1.0, abs(float(np.dot(lig_normal, rec_normal))))))
                    if center_distance <= _PI_STACKING_CUTOFF and (
                        normal_angle <= _PI_PARALLEL_ANGLE or normal_angle >= _PI_EDGE_ON_ANGLE
                    ):
                        atom_index = min(ring, key=lambda i: float(np.linalg.norm(ligand_xyz[i] - rec_center)))
                        receptor_index = min(ring_rec_indices, key=lambda i: float(np.linalg.norm(rec[i][3] - lig_center)))
                        add_interaction("pi_stacking", residue, atom_index, rec[receptor_index][2], center_distance)

                    for atom_index, charge in ligand_charges:
                        if charge > 0:
                            distance = float(np.linalg.norm(ligand_xyz[atom_index] - rec_center))
                            if distance <= _CATION_PI_CUTOFF:
                                receptor_index = min(
                                    ring_rec_indices,
                                    key=lambda i: float(np.linalg.norm(rec[i][3] - ligand_xyz[atom_index])),
                                )
                                add_interaction("cation_pi", residue, atom_index, rec[receptor_index][2], distance)

        for rec_index, charge in protein_charges:
            if charge <= 0:
                continue
            rname, rnum = rec[rec_index][:2]
            for ring in ligand_rings:
                lig_center = ligand_xyz[list(ring)].mean(axis=0)
                distance = float(np.linalg.norm(rec[rec_index][3] - lig_center))
                if distance <= _CATION_PI_CUTOFF:
                    atom_index = min(ring, key=lambda i: float(np.linalg.norm(ligand_xyz[i] - rec[rec_index][3])))
                    add_interaction("cation_pi", f"{rname}{rnum}", atom_index, rec[rec_index][2], distance)

    classified_residues = {
        residue for kind, residue, _, _ in interaction_distances if kind != "contact"
    }
    interactions = [
        DiagramInteraction(kind, residue, ligand_atom, receptor_atom, distance)
        for (kind, residue, ligand_atom, receptor_atom), distance in interaction_distances.items()
        if kind != "contact" or residue not in classified_residues
    ]
    residue_structures = (
        _residue_structures(receptor_pdb, {item.residue for item in interactions})
        if ligand_indices is not None and interactions
        else []
    )
    return ContactReport(residues, polar, interactions, residue_structures, thresholds)
