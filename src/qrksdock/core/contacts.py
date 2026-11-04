"""Simple, transparent contact analysis of a docked pose against the prepared receptor.

This is NOT a full interaction profiler: it lists receptor residues with any heavy atom
within a distance cutoff of the ligand, and N/O atom pairs close enough to be hydrogen-bond
candidates. Full 3D interaction mapping is done in PyMOL by the Technical Lead.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from qrksdock.core import rules

_AD_ELEMENT = {"A": "C", "C": "C", "N": "N", "NA": "N", "NS": "N", "OA": "O", "OS": "O", "O": "O",
               "S": "S", "SA": "S", "P": "P", "F": "F", "CL": "CL", "BR": "BR", "I": "I",
               "HD": "H", "H": "H", "HS": "H"}


@dataclass
class ContactReport:
    residues: list[str] = field(default_factory=list)          # e.g. "TYR50"
    polar: list[tuple[str, str, float]] = field(default_factory=list)   # (ligand atom, residue atom, distance)


def read_receptor_atoms(pdb: Path) -> list[tuple[str, str, str, np.ndarray, str]]:
    atoms = []
    for line in Path(pdb).read_text(errors="replace").splitlines():
        if not line.startswith("ATOM  "):
            continue
        el = (line[76:78].strip() or line[12:16].strip().lstrip("0123456789")[:1]).upper()
        if el == "H":
            continue
        atoms.append((line[17:20].strip(), line[22:27].strip(), line[12:16].strip(),
                      np.array([float(line[30:38]), float(line[38:46]), float(line[46:54])]), el))
    return atoms


def first_pose_atoms(out_pdbqt: Path) -> list[tuple[str, np.ndarray, str]]:
    atoms = []
    for line in Path(out_pdbqt).read_text(errors="replace").splitlines():
        if line.startswith("ENDMDL"):
            break
        if not line.startswith(("ATOM", "HETATM")):
            continue
        ad = line[77:79].strip().upper()
        el = _AD_ELEMENT.get(ad, ad[:1])
        if el == "H":
            continue
        atoms.append((line[12:16].strip(), np.array([float(line[30:38]), float(line[38:46]), float(line[46:54])]), el))
    return atoms


def analyse(receptor_pdb: Path, pose_pdbqt: Path) -> ContactReport:
    cfg = rules.docking_defaults()
    cut, polar_cut = cfg["contact_cutoff_angstrom"], cfg["polar_contact_cutoff_angstrom"]
    rec = read_receptor_atoms(receptor_pdb)
    lig = first_pose_atoms(pose_pdbqt)
    if not rec or not lig:
        return ContactReport()
    rxyz = np.array([a[3] for a in rec])
    lxyz = np.array([a[1] for a in lig])
    d = np.linalg.norm(rxyz[:, None, :] - lxyz[None, :, :], axis=2)
    res_hit: dict[str, int] = {}
    for i in np.where((d <= cut).any(axis=1))[0]:
        name, num = rec[i][0], rec[i][1]
        res_hit.setdefault(f"{name}{num}", int(num.rstrip("ABCDEFGHIJKLMNOPQRSTUVWXYZ") or 0))
    residues = sorted(res_hit, key=lambda k: res_hit[k])
    polar = []
    for j, (lname, _, lel) in enumerate(lig):
        if lel not in ("N", "O"):
            continue
        for i, (rname, rnum, ratom, _, rel) in enumerate(rec):
            if rel in ("N", "O") and d[i, j] <= polar_cut:
                polar.append((lname, f"{rname}{rnum}:{ratom}", float(d[i, j])))
    polar.sort(key=lambda t: t[2])
    return ContactReport(residues, polar)
