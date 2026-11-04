"""Receptor intake and preparation: clean -> pdb2pqr/PROPKA (pH 7.4) -> Meeko PDBQT."""
from __future__ import annotations

import contextlib
import io
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

Log = Callable[[str], None]
STANDARD_RES = {"ALA", "ARG", "ASN", "ASP", "CYS", "GLN", "GLU", "GLY", "HIS", "ILE", "LEU", "LYS",
                "MET", "PHE", "PRO", "SER", "THR", "TRP", "TYR", "VAL"}
WATERS = {"HOH", "WAT", "H2O", "DOD", "TIP"}
METHODS = ("pdb2pqr", "as_is")


class ReceptorError(Exception):
    pass


@dataclass
class PDBSummary:
    chains: dict[str, int]
    n_atoms: int
    hetero: dict[str, int]
    waters: int
    has_hydrogens: bool
    has_altlocs: bool
    warnings: list[str] = field(default_factory=list)

    def text(self) -> str:
        ch = ", ".join(f"{c} ({n} residues)" for c, n in self.chains.items()) or "none"
        het = ", ".join(f"{r} x{n}" for r, n in self.hetero.items()) or "none"
        return f"Chains: {ch}\nAtoms: {self.n_atoms}\nWaters: {self.waters}\nOther hetero groups: {het}"


@dataclass
class PreparedReceptor:
    source: Path
    clean_pdb: Path
    protonated_pdb: Path
    pdbqt: Path
    method: str
    ph: float
    chains_kept: list[str]
    removed: dict[str, int]
    residue_states: dict[str, int]
    warnings: list[str] = field(default_factory=list)


def _records(path: Path):
    for line in Path(path).read_text(errors="replace").splitlines():
        if line.startswith(("ATOM  ", "HETATM")):
            yield line


def inspect_pdb(path: Path) -> PDBSummary:
    chain_res: dict[str, set] = {}
    hetero: Counter = Counter()
    waters, n_atoms = 0, 0
    has_h = has_alt = False
    seen_het: set = set()
    for line in _records(path):
        res, chain, num = line[17:20].strip(), line[21], line[22:27]
        element = (line[76:78].strip() or line[12:16].strip().lstrip("0123456789")[:1]).upper()
        if line[16] not in (" ", "A"):
            has_alt = True
        if line.startswith("ATOM"):
            n_atoms += 1
            chain_res.setdefault(chain, set()).add(num)
            has_h = has_h or element == "H"
        elif res in WATERS:
            if (chain, num) not in seen_het:
                waters += 1
                seen_het.add((chain, num))
        else:
            if (res, chain, num) not in seen_het:
                hetero[res] += 1
                seen_het.add((res, chain, num))
    chains = {c: len(r) for c, r in sorted(chain_res.items())}
    warns = []
    if not chains:
        warns.append("No protein ATOM records found.")
    if waters or hetero:
        warns.append("Waters, ligands, ions and cofactors will be removed during preparation.")
    if has_alt:
        warns.append("Alternate locations found. Location A is kept.")
    return PDBSummary(chains, n_atoms, dict(hetero), waters, has_h, has_alt, warns)


def _clean(src: Path, dst: Path, chains: list[str] | None, strip_h: bool) -> tuple[list[str], dict[str, int]]:
    kept_chains: list[str] = []
    removed: Counter = Counter()
    seen_removed: set = set()
    out = []
    for line in Path(src).read_text(errors="replace").splitlines():
        if line.startswith("ENDMDL"):
            break                                         # first model only (NMR ensembles)
        if not line.startswith(("ATOM  ", "HETATM")):
            continue
        res, chain, num = line[17:20].strip(), line[21], line[22:27]
        if chains and chain not in chains:
            continue
        if line.startswith("HETATM") or res not in STANDARD_RES:
            key = ("HOH" if res in WATERS else res, chain, num)
            if key not in seen_removed:
                seen_removed.add(key)
                removed[key[0]] += 1
            continue
        if line[16] not in (" ", "A"):
            continue
        element = (line[76:78].strip() or line[12:16].strip().lstrip("0123456789")[:1]).upper()
        if strip_h and element == "H":
            continue
        out.append(line[:16] + " " + line[17:])
        if chain not in kept_chains:
            kept_chains.append(chain)
    if not out:
        raise ReceptorError("No protein atoms left after cleaning. Check the chain selection.")
    dst.write_text("\n".join(out) + "\nEND\n")
    return kept_chains, dict(removed)


def _run_pdb2pqr(clean_pdb: Path, outdir: Path, ph: float, log: Log) -> Path:
    from pdb2pqr.main import build_main_parser, main_driver

    out_pdb, out_pqr = outdir / "receptor_H.pdb", outdir / "receptor.pqr"
    args = build_main_parser().parse_args([
        "--ff", "AMBER", "--ffout", "AMBER", "--with-ph", str(ph), "--titration-state-method", "propka",
        "--keep-chain", "--drop-water", "--pdb-output", str(out_pdb), str(clean_pdb), str(out_pqr)])
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            main_driver(args)
    except SystemExit as exc:
        raise ReceptorError(f"pdb2pqr stopped (code {exc.code}):\n{buf.getvalue()[-600:]}") from exc
    except Exception as exc:                                           # noqa: BLE001
        raise ReceptorError(f"pdb2pqr failed: {exc}\n{buf.getvalue()[-600:]}") from exc
    (outdir / "pdb2pqr.log").write_text(buf.getvalue(), encoding="utf-8")
    if not out_pdb.exists():
        raise ReceptorError("pdb2pqr did not produce a protonated structure.")
    log(f"  pdb2pqr + PROPKA finished (pH {ph})")
    return out_pdb


def _run_meeko_receptor(pdb: Path, base: Path, allow_bad_res: bool) -> Path:
    from meeko.cli import mk_prepare_receptor

    argv = ["mk_prepare_receptor", "--read_pdb", str(pdb), "-o", str(base), "-p"]
    if allow_bad_res:
        argv.append("--delete_bad_res")
    old, buf = sys.argv, io.StringIO()
    sys.argv = argv
    try:
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            mk_prepare_receptor.main()
    except SystemExit as exc:
        if exc.code not in (0, None):
            raise ReceptorError(f"Meeko could not prepare the receptor:\n{buf.getvalue()[-800:]}") from exc
    except Exception as exc:                                           # noqa: BLE001
        raise ReceptorError(f"Meeko could not prepare the receptor: {exc}\n{buf.getvalue()[-800:]}") from exc
    finally:
        sys.argv = old
    out = Path(str(base) + ".pdbqt")
    if not out.exists():
        raise ReceptorError(f"Meeko produced no PDBQT file:\n{buf.getvalue()[-800:]}")
    return out


def prepare_receptor(pdb_path: Path, outdir: Path, ph: float = 7.4, method: str = "pdb2pqr",
                     chains: list[str] | None = None, allow_bad_res: bool = False,
                     log: Log | None = None) -> PreparedReceptor:
    log = log or (lambda s: None)
    if method not in METHODS:
        raise ReceptorError(f"Unknown protonation method '{method}'")
    outdir.mkdir(parents=True, exist_ok=True)
    log("Cleaning structure (first model, location A, protein atoms only)")
    clean = outdir / "receptor_clean.pdb"
    kept, removed = _clean(Path(pdb_path), clean, chains, strip_h=(method == "pdb2pqr"))
    warnings: list[str] = []
    if removed:
        warnings.append("Removed from the receptor: " + ", ".join(f"{k} x{v}" for k, v in sorted(removed.items())) + ".")
    if method == "pdb2pqr":
        protonated = _run_pdb2pqr(clean, outdir, ph, log)
    else:
        protonated = clean
        if not inspect_pdb(clean).has_hydrogens:
            raise ReceptorError("'Already protonated' was selected, but the structure has no hydrogens.")
        warnings.append("Protonation was supplied by the user (for example from H++); pH not re-assigned.")
    log("  Meeko receptor preparation")
    pdbqt = _run_meeko_receptor(protonated, outdir / "receptor", allow_bad_res)
    states: Counter = Counter()
    seen: set = set()
    for line in _records(protonated):
        key = (line[21], line[22:27])
        if key not in seen:
            seen.add(key)
            if line[17:20] in ("HID", "HIE", "HIP", "CYX", "CYM", "ASH", "GLH", "LYN", "HIS"):
                states[line[17:20]] += 1
    return PreparedReceptor(Path(pdb_path), clean, protonated, pdbqt, method, ph, kept, removed,
                            dict(states), warnings)
