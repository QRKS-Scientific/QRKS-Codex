"""Ligand intake, checks and preparation (Scrubber -> Meeko).

Small molecules arrive as SMILES (or SDF) with a name. Peptides arrive as one-letter
sequences (2-6 residues). Every ligand is checked, protonated at the target pH, given a
3D conformer by the Scrubber, and written as PDBQT by Meeko.
"""
from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from rdkit import Chem, RDLogger
from rdkit.Chem import Descriptors, rdMolDescriptors

from qrksdock.core import rules

Log = Callable[[str], None]
AMINO = set("ACDEFGHIKLMNPQRSTVWY")
STEREO_POLICIES = ("warn", "block", "enumerate")
_NAME_BAD = re.compile(r"[^A-Za-z0-9_.\-]+")


class LigandError(Exception):
    pass


@dataclass
class LigandInput:
    name: str
    kind: str                 # "small_molecule" | "peptide"
    smiles: str = ""
    sequence: str = ""


@dataclass
class LigandCheck:
    name: str
    kind: str
    ok: bool
    smiles: str = ""
    heavy_atoms: int = 0
    mass: float = 0.0
    rot_bonds: int = 0
    unspecified_centers: int = 0
    unspecified_double_bonds: int = 0
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def stereo_text(self) -> str:
        if self.unspecified_centers or self.unspecified_double_bonds:
            bits = []
            if self.unspecified_centers:
                bits.append(f"{self.unspecified_centers} undefined centre(s)")
            if self.unspecified_double_bonds:
                bits.append(f"{self.unspecified_double_bonds} undefined double bond(s)")
            return ", ".join(bits)
        return "defined"


@dataclass
class PreparedState:
    ligand: str               # parent ligand name
    state: str                # state name (== ligand name when there is one state)
    kind: str
    pdbqt: Path
    sdf: Path
    smiles: str
    charge: int
    rot_bonds: int
    warnings: list[str] = field(default_factory=list)


@dataclass
class ReferenceLigand:
    pdbqt: Path
    sdf: Path
    mol: Chem.Mol             # heavy atoms only, crystal coordinates, crystal bond orders
    centroid: tuple[float, float, float]
    extent: tuple[float, float, float]


# ---------------------------------------------------------------------------------
# parsing
# ---------------------------------------------------------------------------------
def sanitize_name(raw: str, fallback: str) -> str:
    name = _NAME_BAD.sub("_", raw.strip()).strip("._-")
    return name[:40] if name else fallback


def parse_smiles_text(text: str) -> list[LigandInput]:
    """Lines of 'SMILES name' (space, tab or comma separated). '#' starts a comment."""
    out: list[LigandInput] = []
    for i, line in enumerate(text.splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = re.split(r"[,\t ]+", line, maxsplit=1)
        if i == 1 and parts[0].lower() == "smiles":
            continue                                    # CSV header row
        smiles = parts[0]
        name = sanitize_name(parts[1] if len(parts) > 1 else "", f"ligand_{len(out) + 1:02d}")
        out.append(LigandInput(name=name, kind="small_molecule", smiles=smiles))
    return out


def parse_peptide_text(text: str) -> list[LigandInput]:
    """Lines of 'SEQUENCE [name]' using one-letter codes. '#' starts a comment."""
    out: list[LigandInput] = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = re.split(r"[,\t ]+", line, maxsplit=1)
        seq = parts[0].upper()
        name = sanitize_name(parts[1] if len(parts) > 1 else "", seq)
        out.append(LigandInput(name=name, kind="peptide", sequence=seq))
    return out


def read_ligand_file(path: Path) -> tuple[str, list[LigandInput]]:
    """Read .smi/.txt/.csv text or an .sdf. Returns (text_for_editor, inputs)."""
    path = Path(path)
    if path.suffix.lower() in (".sdf", ".mol"):
        lines = []
        for i, m in enumerate(Chem.SDMolSupplier(str(path), removeHs=False), 1):
            if m is None:
                continue
            name = m.GetProp("_Name") if m.HasProp("_Name") and m.GetProp("_Name").strip() else f"ligand_{i:02d}"
            lines.append(f"{Chem.MolToSmiles(Chem.RemoveHs(m))} {sanitize_name(name, f'ligand_{i:02d}')}")
        text = "\n".join(lines)
    else:
        text = path.read_text(encoding="utf-8-sig", errors="replace")
    return text, parse_smiles_text(text)


def peptide_mol(seq: str) -> Chem.Mol:
    mol = Chem.MolFromSequence(seq)
    if mol is None:
        raise LigandError(f"Could not build peptide '{seq}'")
    return mol


def _mol_for(inp: LigandInput) -> Chem.Mol | None:
    if inp.kind == "peptide":
        return peptide_mol(inp.sequence)
    return Chem.MolFromSmiles(inp.smiles)


# ---------------------------------------------------------------------------------
# checks
# ---------------------------------------------------------------------------------
def check_ligands(inputs: list[LigandInput], stereo_policy: str = "warn") -> list[LigandCheck]:
    RDLogger.DisableLog("rdApp.*")
    pep = rules.peptide_rules()
    seen: dict[str, int] = {}
    results: list[LigandCheck] = []
    for inp in inputs:
        chk = LigandCheck(name=inp.name, kind=inp.kind, ok=True)
        seen[inp.name] = seen.get(inp.name, 0) + 1
        if seen[inp.name] > 1:
            chk.errors.append("Duplicate name. Every ligand needs a unique name.")
        if inp.kind == "peptide":
            seq = inp.sequence
            bad = sorted(set(seq) - AMINO)
            if bad:
                chk.errors.append(f"Unsupported residue code(s): {', '.join(bad)}. Use the 20 standard one-letter codes.")
            elif not pep["min_residues"] <= len(seq) <= pep["max_residues"]:
                chk.errors.append(f"Peptides must be {pep['min_residues']}-{pep['max_residues']} residues (got {len(seq)}).")
        mol = None if chk.errors else _mol_for(inp)
        if not chk.errors and mol is None:
            chk.errors.append("Could not read this structure. Check the SMILES.")
        if mol is not None:
            chk.smiles = Chem.MolToSmiles(mol)
            chk.heavy_atoms = mol.GetNumHeavyAtoms()
            chk.mass = round(Descriptors.MolWt(mol), 2)
            chk.rot_bonds = rdMolDescriptors.CalcNumRotatableBonds(mol)
            if len(Chem.GetMolFrags(mol)) > 1:
                chk.warnings.append("Contains several fragments (salt or counter-ion). Only the largest is docked.")
            for si in Chem.FindPotentialStereo(mol):
                if si.specified == Chem.StereoSpecified.Unspecified:
                    if si.type == Chem.StereoType.Atom_Tetrahedral:
                        chk.unspecified_centers += 1
                    elif si.type == Chem.StereoType.Bond_Double:
                        chk.unspecified_double_bonds += 1
            if chk.unspecified_centers or chk.unspecified_double_bonds:
                msg = f"Stereochemistry not fully defined ({chk.stereo_text})."
                if stereo_policy == "block":
                    chk.errors.append(msg + " Define it in the SMILES, or change the stereo policy.")
                elif stereo_policy == "enumerate":
                    chk.warnings.append(msg + " All stereoisomers will be docked as separate states.")
                else:
                    chk.warnings.append(msg + " An arbitrary stereoisomer will be docked; the report will say so.")
            if inp.kind == "peptide":
                if chk.mass > pep["max_mass_da"]:
                    chk.errors.append(f"Mass {chk.mass:.0f} Da is above the {pep['max_mass_da']} Da peptide limit.")
                if len(inp.sequence) >= 5:
                    chk.warnings.append("Peptides of 5-6 residues are highly flexible; Vina poses are less reliable.")
            if chk.rot_bonds > 32:
                chk.errors.append(f"{chk.rot_bonds} rotatable bonds is more than Vina can handle (32).")
            elif chk.rot_bonds > 12:
                chk.warnings.append(f"{chk.rot_bonds} rotatable bonds: flexible ligand, use higher exhaustiveness.")
        chk.ok = not chk.errors
        results.append(chk)
    return results


# ---------------------------------------------------------------------------------
# preparation
# ---------------------------------------------------------------------------------
def _largest_fragment(mol: Chem.Mol) -> Chem.Mol:
    frags = Chem.GetMolFrags(mol, asMols=True)
    return max(frags, key=lambda m: m.GetNumHeavyAtoms()) if len(frags) > 1 else mol


def prepare_ligand(inp: LigandInput, outdir: Path, ph: float, seed: int,
                   stereo_policy: str = "warn", log: Log | None = None) -> list[PreparedState]:
    """Protonate, build 3D, and write PDBQT for each protonation/tautomer state."""
    from meeko import MoleculePreparation, PDBQTWriterLegacy
    from molscrub import Scrub

    log = log or (lambda s: None)
    RDLogger.DisableLog("rdApp.*")
    cfg = rules.docking_defaults()
    outdir.mkdir(parents=True, exist_ok=True)

    mol = _mol_for(inp)
    if mol is None:
        raise LigandError(f"{inp.name}: could not read structure")
    mol = _largest_fragment(mol)
    mol.SetProp("_Name", inp.name)

    enumerate_stereo = stereo_policy == "enumerate"
    scrub = Scrub(ph_low=ph, ph_high=ph, etkdg_rng_seed=seed, do_stereoisomers=enumerate_stereo)
    try:
        states = list(scrub(mol))
    except Exception as exc:                                   # noqa: BLE001
        raise LigandError(f"{inp.name}: protonation/3D generation failed ({exc})") from exc
    if not states:
        raise LigandError(f"{inp.name}: the Scrubber returned no valid states")

    cap = cfg["max_stereoisomers"] if enumerate_stereo else cfg["max_states_per_ligand"]
    notes: list[str] = []
    if len(states) > cap:
        notes.append(f"{len(states)} states generated; the first {cap} are docked.")
        states = states[:cap]

    prepared: list[PreparedState] = []
    for i, st in enumerate(states, 1):
        state_name = inp.name if len(states) == 1 else f"{inp.name}_s{i}"
        st.SetProp("_Name", state_name)
        setups = MoleculePreparation().prepare(st)
        pdbqt, ok, err = PDBQTWriterLegacy.write_string(setups[0])
        if not ok:
            raise LigandError(f"{state_name}: Meeko could not write PDBQT ({err})")
        pdbqt_path = outdir / f"{state_name}.pdbqt"
        sdf_path = outdir / f"{state_name}.sdf"
        pdbqt_path.write_text(pdbqt, encoding="utf-8")
        w = Chem.SDWriter(str(sdf_path))
        w.write(st)
        w.close()
        torsdof = next((int(l.split()[1]) for l in pdbqt.splitlines() if l.startswith("TORSDOF")), 0)
        prepared.append(PreparedState(
            ligand=inp.name, state=state_name, kind=inp.kind, pdbqt=pdbqt_path, sdf=sdf_path,
            smiles=Chem.MolToSmiles(Chem.RemoveHs(st)), charge=Chem.GetFormalCharge(st),
            rot_bonds=torsdof, warnings=list(notes)))
        log(f"  {state_name}: charge {prepared[-1].charge:+d}, {torsdof} torsions")
    return prepared


def prepare_reference_ligand(path: Path, outdir: Path) -> ReferenceLigand:
    """Prepare the co-crystal ligand for redocking, keeping its crystal coordinates."""
    from meeko import MoleculePreparation, PDBQTWriterLegacy

    RDLogger.DisableLog("rdApp.*")
    path = Path(path)
    if path.suffix.lower() == ".mol2":
        mol = Chem.MolFromMol2File(str(path), removeHs=False)
    else:
        mol = next((m for m in Chem.SDMolSupplier(str(path), removeHs=False) if m is not None), None)
    if mol is None:
        raise LigandError("Could not read the reference ligand. Export it from PyMOL as an .sdf file "
                          "(a PDB file loses the bond orders).")
    if mol.GetNumConformers() == 0 or not mol.GetConformer().Is3D():
        raise LigandError("The reference ligand has no 3D coordinates.")
    mol = _largest_fragment(mol)
    heavy = Chem.RemoveHs(mol)
    mol_h = Chem.AddHs(mol, addCoords=True)                    # keeps heavy-atom crystal coordinates
    mol_h.SetProp("_Name", "reference")

    outdir.mkdir(parents=True, exist_ok=True)
    setups = MoleculePreparation().prepare(mol_h)
    pdbqt, ok, err = PDBQTWriterLegacy.write_string(setups[0])
    if not ok:
        raise LigandError(f"Reference ligand could not be prepared: {err}")
    pdbqt_path = outdir / "reference.pdbqt"
    pdbqt_path.write_text(pdbqt, encoding="utf-8")
    sdf_path = outdir / "reference.sdf"
    w = Chem.SDWriter(str(sdf_path))
    w.write(mol_h)
    w.close()

    xyz = heavy.GetConformer().GetPositions()
    centroid = tuple(float(v) for v in xyz.mean(axis=0))
    extent = tuple(float(v) for v in (xyz.max(axis=0) - xyz.min(axis=0)))
    return ReferenceLigand(pdbqt=pdbqt_path, sdf=sdf_path, mol=heavy, centroid=centroid, extent=extent)
