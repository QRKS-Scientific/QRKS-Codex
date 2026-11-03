"""Redocking validation: dock the co-crystal ligand back and measure RMSD to the crystal pose."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from rdkit import Chem, RDLogger
from rdkit.Chem import rdMolAlign

from qrksdock.core import rules


@dataclass
class ValidationResult:
    rmsd_top: float            # top-ranked pose vs crystal, heavy atoms, symmetry-corrected, no re-alignment
    rmsd_best: float           # lowest RMSD among all returned poses
    best_pose: int
    threshold: float
    passed: bool               # top-ranked pose within threshold
    affinity_top: float
    n_poses: int

    def text(self) -> str:
        verdict = "PASSED" if self.passed else "NOT PASSED"
        return (f"Redocking {verdict}: top pose RMSD {self.rmsd_top:.2f} Å "
                f"(threshold {self.threshold:.1f} Å); best of {self.n_poses} poses "
                f"{self.rmsd_best:.2f} Å (pose {self.best_pose}).")


def pose_mol(out_pdbqt: Path) -> Chem.Mol:
    """Poses from a Vina output PDBQT as one RDKit molecule with one conformer per pose."""
    from meeko import PDBQTMolecule, RDKitMolCreate

    RDLogger.DisableLog("rdApp.*")
    pm = PDBQTMolecule(Path(out_pdbqt).read_text(), skip_typing=True)
    mols = RDKitMolCreate.from_pdbqt_mol(pm)
    if not mols or mols[0] is None:
        raise ValueError(f"Could not rebuild the docked molecule from {out_pdbqt}")
    return mols[0]


def rmsd_per_pose(out_pdbqt: Path, reference_heavy: Chem.Mol) -> list[float]:
    mol = Chem.RemoveHs(pose_mol(out_pdbqt))
    return [float(rdMolAlign.CalcRMS(mol, reference_heavy, prbId=cid, refId=-1))
            for cid in range(mol.GetNumConformers())]


def evaluate(out_pdbqt: Path, reference_heavy: Chem.Mol, affinities: list[float]) -> ValidationResult:
    rms = rmsd_per_pose(out_pdbqt, reference_heavy)
    thr = rules.docking_defaults()["redock_rmsd_threshold_angstrom"]
    best = min(range(len(rms)), key=rms.__getitem__)
    return ValidationResult(rmsd_top=rms[0], rmsd_best=rms[best], best_pose=best + 1, threshold=thr,
                            passed=rms[0] <= thr, affinity_top=affinities[0], n_poses=len(rms))
