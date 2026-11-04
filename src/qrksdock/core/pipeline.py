"""The QRKSDock workflow, from ticket to results.

`Project` is what the GUI and the command line both drive. It keeps its state in
`work/state.json` inside the ticket folder, so closing the app and reopening the ticket
picks up where you left off. Paths are stored relative to the ticket folder so the folder
can move between laptops and Google Drive.
"""
from __future__ import annotations

import csv
import json
import shutil
import threading
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable

from rdkit import Chem

from qrksdock import __version__
from qrksdock.core import box as boxmod
from qrksdock.core import contacts, ligands, manifest, receptor, rules, thermo, validation, vina_runner
from qrksdock.core.box import Box
from qrksdock.core.tickets import Ticket

Log = Callable[[str], None]
Progress = Callable[[float, str], None]


class Cancelled(Exception):
    pass


class PipelineError(Exception):
    pass


@dataclass
class DockParams:
    exhaustiveness: int = 16
    num_modes: int = 10                 # top 10 poses per ligand
    energy_range: float = 10.0          # wide enough that Vina does not cut the list short
    seed: int | None = None             # None: Vina picks its own; the seed is read back from its log
    cpu: int = 1
    ph: float = 7.4


@dataclass
class LigandResult:
    ligand: str                         # internal id (the name as first entered); never changes
    state: str
    kind: str
    best_affinity: float
    affinities: list[float]
    out_pdbqt: str
    poses_sdf: str
    rot_bonds: int
    smiles: str
    charge: int
    contact_residues: list[str] = field(default_factory=list)
    polar_contacts: list[list] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    seconds: float = 0.0
    rmsd_lb: list[float] = field(default_factory=list)
    rmsd_ub: list[float] = field(default_factory=list)
    seed: int | None = None
    log: str = ""                       # raw Vina console output for this ligand

    @property
    def pkd(self) -> float:
        return thermo.estimate_pkd(self.best_affinity)


def _noop_log(_: str) -> None:
    pass


def _noop_progress(_f: float, _m: str) -> None:
    pass


class Project:
    def __init__(self, ticket: Ticket, actor: str):
        self.ticket = ticket
        self.actor = actor
        self.s: dict[str, Any] = {}
        self.load()

    # ---- persistence ----------------------------------------------------------------
    @property
    def state_file(self) -> Path:
        return self.ticket.sub("work") / "state.json"

    def load(self) -> None:
        if self.state_file.exists():
            try:
                self.s = json.loads(self.state_file.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                self.s = {}

    def save(self) -> None:
        tmp = self.state_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.s, indent=2, default=str), encoding="utf-8")
        tmp.replace(self.state_file)

    def _rel(self, p: Path | str) -> str:
        return Path(p).resolve().relative_to(self.ticket.path.resolve()).as_posix()

    def _abs(self, rel: str) -> Path:
        return self.ticket.path / rel

    # ---- state accessors ----------------------------------------------------------------
    @property
    def box(self) -> Box | None:
        return Box.from_dict(self.s["box"]) if "box" in self.s else None

    @property
    def receptor_ready(self) -> bool:
        r = self.s.get("receptor")
        return bool(r) and self._abs(r["pdbqt"]).exists()

    @property
    def reference_ready(self) -> bool:
        return "reference" in self.s and self._abs(self.s["reference"]["sdf"]).exists()

    @property
    def ligands_ready(self) -> bool:
        return bool(self.s.get("prepared"))

    @property
    def results(self) -> list[LigandResult]:
        return [LigandResult(**r) for r in self.s.get("results", [])]

    @property
    def validation(self) -> validation.ValidationResult | None:
        v = self.s.get("validation")
        return validation.ValidationResult(**v) if v else None

    def load_reference(self) -> ligands.ReferenceLigand:
        sdf = self._abs(self.s["reference"]["sdf"])
        mol_h = next(m for m in Chem.SDMolSupplier(str(sdf), removeHs=False) if m is not None)
        heavy = Chem.RemoveHs(mol_h)
        xyz = heavy.GetConformer().GetPositions()
        return ligands.ReferenceLigand(self._abs(self.s["reference"]["pdbqt"]), sdf, heavy,
                                       tuple(float(v) for v in xyz.mean(axis=0)),
                                       tuple(float(v) for v in (xyz.max(axis=0) - xyz.min(axis=0))))

    # ---- step 1: receptor, reference ligand and box ---------------------------------------
    def prepare_receptor(self, pdb_path: Path, *, method: str = "pdb2pqr", chains: list[str] | None = None,
                         ph: float = 7.4, box_mode: str = "blind", reference_path: Path | None = None,
                         manual_box: tuple[tuple, tuple] | None = None, allow_bad_res: bool = False,
                         log: Log = _noop_log) -> dict[str, Any]:
        inp = self.ticket.sub("input")
        src = inp / f"receptor_original{Path(pdb_path).suffix or '.pdb'}"
        if Path(pdb_path).resolve() != src.resolve():
            shutil.copy2(pdb_path, src)
        work = self.ticket.sub("work")
        rec_dir = work / "receptor"
        if rec_dir.exists():
            shutil.rmtree(rec_dir)
        pr = receptor.prepare_receptor(src, rec_dir, ph=ph, method=method, chains=chains,
                                       allow_bad_res=allow_bad_res, log=log)
        warnings = list(pr.warnings)

        self.s.pop("reference", None)
        ref = None
        if reference_path:
            log("Preparing the reference (co-crystal) ligand")
            rsrc = inp / f"reference_ligand{Path(reference_path).suffix}"
            if Path(reference_path).resolve() != rsrc.resolve():
                shutil.copy2(reference_path, rsrc)
            ref_dir = work / "reference"
            if ref_dir.exists():
                shutil.rmtree(ref_dir)
            ref = ligands.prepare_reference_ligand(rsrc, ref_dir)
            self.s["reference"] = {"source": self._rel(rsrc), "pdbqt": self._rel(ref.pdbqt), "sdf": self._rel(ref.sdf)}

        if box_mode == "reference":
            if ref is None:
                raise PipelineError("A box around the reference ligand needs a reference ligand file.")
            box = boxmod.box_from_reference(ref.centroid, ref.extent)
        elif box_mode == "manual":
            if not manual_box:
                raise PipelineError("Enter the box centre and size.")
            box = boxmod.box_manual(*manual_box)
        else:
            box = boxmod.box_blind(pr.protonated_pdb)
        warnings += boxmod.box_warnings(box)

        self.s["receptor"] = {
            "source": self._rel(src), "clean_pdb": self._rel(pr.clean_pdb), "protonated_pdb": self._rel(pr.protonated_pdb),
            "pdbqt": self._rel(pr.pdbqt), "method": pr.method, "ph": pr.ph, "chains_kept": pr.chains_kept,
            "removed": pr.removed, "residue_states": pr.residue_states, "warnings": warnings,
        }
        self.s["box"] = box.to_dict()
        for k in ("validation", "results"):                     # downstream results are now stale
            self.s.pop(k, None)
        self.save()
        self.ticket.add_event(self.actor, "receptor_prepared", {"method": method, "ph": ph, "box": box.mode})
        log(box.summary())
        return {"box": box, "warnings": warnings, "recommended_exhaustiveness": boxmod.recommended_exhaustiveness(box)}

    # ---- step 2: ligands -------------------------------------------------------------------------
    def prepare_ligands(self, small_text: str, peptide_text: str, *, stereo_policy: str = "warn",
                        ph: float = 7.4, seed: int = 42, log: Log = _noop_log,
                        progress: Progress = _noop_progress) -> list[ligands.LigandCheck]:
        inputs = ligands.parse_smiles_text(small_text) + ligands.parse_peptide_text(peptide_text)
        if not inputs:
            raise PipelineError("Add at least one ligand (SMILES) or peptide (sequence).")
        checks = ligands.check_ligands(inputs, stereo_policy)
        bad = [c for c in checks if not c.ok]
        if bad:
            raise PipelineError("Fix these ligands first:\n" + "\n".join(f"  {c.name}: {'; '.join(c.errors)}" for c in bad))
        n_small = sum(1 for i in inputs if i.kind == "small_molecule")
        issues = self.ticket.check_limits(n_small, len(inputs) - n_small)
        if issues:
            raise PipelineError("Package limit exceeded:\n  " + "\n  ".join(issues))

        inp = self.ticket.sub("input")
        (inp / "ligands_small_molecules.smi").write_text(small_text, encoding="utf-8")
        (inp / "ligands_peptides.txt").write_text(peptide_text, encoding="utf-8")
        lig_dir = self.ticket.sub("work") / "ligands"
        if lig_dir.exists():
            shutil.rmtree(lig_dir)

        prepared: list[ligands.PreparedState] = []
        for i, item in enumerate(inputs):
            progress(i / len(inputs), f"Preparing {item.name}")
            log(f"Preparing {item.name} ({item.kind.replace('_', ' ')})")
            prepared += ligands.prepare_ligand(item, lig_dir, ph, seed, stereo_policy, log)
        progress(1.0, "Ligands ready")

        check_by_name = {c.name: c for c in checks}
        self.s["ligand_inputs"] = [asdict(i) for i in inputs]
        self.s["ligand_checks"] = [asdict(c) for c in checks]
        self.s["stereo_policy"] = stereo_policy
        self.s["prepared"] = [
            {"ligand": p.ligand, "state": p.state, "kind": p.kind, "pdbqt": self._rel(p.pdbqt), "sdf": self._rel(p.sdf),
             "smiles": p.smiles, "charge": p.charge, "rot_bonds": p.rot_bonds,
             "warnings": p.warnings + check_by_name[p.ligand].warnings} for p in prepared]
        for k in ("validation", "results"):
            self.s.pop(k, None)
        self.save()
        self.ticket.add_event(self.actor, "ligands_prepared", {"ligands": len(inputs), "states": len(prepared)})
        return checks

    # ---- shared docking plumbing -----------------------------------------------------------
    def _exe(self, user_path: str | None) -> tuple[Path, str]:
        exe = vina_runner.find_vina(user_path)
        if exe is None:
            raise PipelineError("AutoDock Vina was not found. Use Help > System check, or choose its location in Settings.")
        return exe, vina_runner.vina_version(exe)

    def _vina(self, exe: Path, ligand_pdbqt: Path, out: Path, params: DockParams, progress_cb, cancel):
        try:
            return vina_runner.run_vina(
                exe, self._abs(self.s["receptor"]["pdbqt"]), ligand_pdbqt, self.box, out,
                exhaustiveness=params.exhaustiveness, num_modes=params.num_modes, energy_range=params.energy_range,
                seed=params.seed, cpu=params.cpu, progress=progress_cb, cancel=cancel)
        except vina_runner.VinaCancelled as exc:
            raise Cancelled() from exc

    # ---- step 3a: redocking validation ---------------------------------------------------------
    def run_validation(self, params: DockParams, *, vina_path: str | None = None, log: Log = _noop_log,
                       progress: Progress = _noop_progress, cancel: threading.Event | None = None
                       ) -> validation.ValidationResult:
        if not (self.receptor_ready and self.reference_ready and self.box):
            raise PipelineError("Validation needs a prepared receptor and a reference ligand.")
        self.ticket.check_can_run(self.actor)
        exe, _ = self._exe(vina_path)
        ref = self.load_reference()
        out_dir = self.ticket.sub("work") / "validation"
        out_dir.mkdir(exist_ok=True)
        log("Redocking the reference ligand")
        run = self._vina(exe, ref.pdbqt, out_dir / "redock_out.pdbqt", params,
                         lambda f: progress(f, "Redocking reference ligand"), cancel)
        (out_dir / "redock_vina.log").write_text(run.log_text, encoding="utf-8")
        val = validation.evaluate(run.out_pdbqt, ref.mol, [p.affinity for p in run.poses])
        self.s["validation"] = asdict(val)
        self.s["validation_params"] = {**asdict(params), "seed_used": run.seed}
        self.save()
        self.ticket.add_event(self.actor, "validation_completed", {"rmsd_top": round(val.rmsd_top, 3), "passed": val.passed})
        log(val.text())
        return val

    # ---- step 3b: docking ---------------------------------------------------------------------------
    def run_docking(self, params: DockParams, *, vina_path: str | None = None, log: Log = _noop_log,
                    progress: Progress = _noop_progress, cancel: threading.Event | None = None) -> list[LigandResult]:
        if not (self.receptor_ready and self.ligands_ready and self.box):
            raise PipelineError("Prepare the receptor and the ligands before docking.")
        self.ticket.check_can_run(self.actor)
        exe, vina_ver = self._exe(vina_path)
        prepared = self.s["prepared"]
        dock_dir = self.ticket.sub("work") / "docking"
        (dock_dir / "logs").mkdir(parents=True, exist_ok=True)
        rec_pdb = self._abs(self.s["receptor"]["protonated_pdb"])
        results: list[LigandResult] = []
        n = len(prepared)
        for i, p in enumerate(prepared):
            if cancel is not None and cancel.is_set():
                raise Cancelled()
            log(f"Docking {p['state']} ({i + 1}/{n})")
            out = dock_dir / f"{p['state']}_out.pdbqt"
            run = self._vina(exe, self._abs(p["pdbqt"]), out, params,
                             lambda f, i=i, name=p["state"]: progress((i + f) / n, f"Docking {name} ({i + 1}/{n})"), cancel)
            raw_log = dock_dir / "logs" / f"{p['state']}.log"
            raw_log.write_text(run.log_text, encoding="utf-8")
            cr = contacts.analyse(rec_pdb, out)
            results.append(LigandResult(
                ligand=p["ligand"], state=p["state"], kind=p["kind"], best_affinity=run.poses[0].affinity,
                affinities=[x.affinity for x in run.poses], out_pdbqt=self._rel(out), poses_sdf="", rot_bonds=p["rot_bonds"],
                smiles=p["smiles"], charge=p["charge"], contact_residues=cr.residues,
                polar_contacts=[[a, b, round(d, 2)] for a, b, d in cr.polar], warnings=p["warnings"],
                seconds=round(run.seconds, 1), rmsd_lb=[x.rmsd_lb for x in run.poses], rmsd_ub=[x.rmsd_ub for x in run.poses],
                seed=run.seed, log=self._rel(raw_log)))
            log(f"  {len(run.poses)} poses, best {run.poses[0].affinity:.2f} kcal/mol, {run.seconds:.0f}s (Vina seed {run.seed})")
            progress((i + 1) / n, f"Finished {p['state']}")

        self.s["results"] = [asdict(r) for r in results]
        self.s["dock_params"] = asdict(params)
        self.s["vina_version"] = vina_ver
        self.s.pop("names", None)                               # a fresh run starts with the original names
        self.save()
        run_id = self._write_manifest(params, vina_ver)
        self.export_results()
        self.ticket.add_event(self.actor, "run_completed", {"run_id": run_id, "ligands": n, "vina": vina_ver})
        log(f"Run complete. Run ID {run_id}")
        return results

    # ---- names (editable in the results table) ---------------------------------------------------
    def ligand_ids(self) -> list[str]:
        seen: list[str] = []
        for r in self.results:
            if r.ligand not in seen:
                seen.append(r.ligand)
        return seen

    def display_ligand(self, ligand_id: str) -> str:
        return self.s.get("names", {}).get(ligand_id, ligand_id)

    def display_state(self, r: LigandResult) -> str:
        base = self.display_ligand(r.ligand)
        return base + r.state[len(r.ligand):] if r.state.startswith(r.ligand) else r.state

    def rename_ligand(self, ligand_id: str, new_name: str) -> str:
        if ligand_id not in self.ligand_ids():
            raise PipelineError(f"Unknown ligand '{ligand_id}'.")
        clean = ligands.sanitize_name(new_name, "")
        if not clean:
            raise PipelineError("A name needs at least one letter or digit. Allowed characters: letters, digits, _ . -")
        taken = {self.display_ligand(l).lower() for l in self.ligand_ids() if l != ligand_id}
        if clean.lower() in taken:
            raise PipelineError(f"'{clean}' is already used by another ligand.")
        old = self.display_ligand(ligand_id)
        if clean != old:
            self.s.setdefault("names", {})[ligand_id] = clean
            self.save()
            self.export_results()
            self.ticket.add_event(self.actor, "ligand_renamed", {"from": old, "to": clean})
        return clean

    # ---- outputs ----------------------------------------------------------------------------------------
    def best_per_ligand(self) -> list[LigandResult]:
        best: dict[str, LigandResult] = {}
        for r in self.results:
            if r.ligand not in best or r.best_affinity < best[r.ligand].best_affinity:
                best[r.ligand] = r
        return sorted(best.values(), key=lambda r: r.best_affinity)

    def export_results(self) -> None:
        """(Re)write every client-facing output using the current ligand names."""
        results = self.results
        if not results:
            return
        res_dir = self.ticket.sub("results")
        ordered = sorted(results, key=lambda r: r.best_affinity)
        ncol = max(len(r.affinities) for r in results)
        with open(res_dir / "results.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["ligand", "state", "kind", "best_affinity_kcal_per_mol", "estimated_pKd", "poses_returned"]
                       + [f"pose_{k}_kcal_per_mol" for k in range(1, ncol + 1)]
                       + ["contact_residues_4A", "polar_contacts_3.5A", "torsions", "net_charge", "vina_seed", "warnings"])
            for r in ordered:
                aff = [f"{a:.3f}" for a in r.affinities] + [""] * (ncol - len(r.affinities))
                w.writerow([self.display_ligand(r.ligand), self.display_state(r), r.kind, f"{r.best_affinity:.3f}", f"{r.pkd:.2f}",
                            len(r.affinities)] + aff + [" ".join(r.contact_residues),
                            "; ".join(f"{x[0]}-{x[1]} {x[2]}A" for x in r.polar_contacts), r.rot_bonds, r.charge, r.seed,
                            " | ".join(r.warnings)])
        with open(res_dir / "poses.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["ligand", "state", "pose", "affinity_kcal_per_mol", "estimated_pKd", "rmsd_lb", "rmsd_ub"])
            for r in ordered:
                for k, a in enumerate(r.affinities):
                    w.writerow([self.display_ligand(r.ligand), self.display_state(r), k + 1, f"{a:.3f}",
                                f"{thermo.estimate_pkd(a):.2f}", f"{r.rmsd_lb[k]:.3f}" if k < len(r.rmsd_lb) else "",
                                f"{r.rmsd_ub[k]:.3f}" if k < len(r.rmsd_ub) else ""])
        pose_dir = res_dir / "poses"
        pose_dir.mkdir(exist_ok=True)
        for old in pose_dir.glob("*.sdf"):
            old.unlink()
        for r in results:                                      # SDF keeps bond orders, ready for PyMOL
            name = self.display_state(r)
            try:
                pm = validation.pose_mol(self._abs(r.out_pdbqt))
                w = Chem.SDWriter(str(pose_dir / f"{name}_poses.sdf"))
                for cid in range(pm.GetNumConformers()):
                    pm.SetProp("_Name", f"{name}_pose{cid + 1}")
                    pm.SetProp("vina_affinity_kcal_mol", f"{r.affinities[cid]:.3f}" if cid < len(r.affinities) else "")
                    w.write(pm, confId=cid)
                w.close()
            except Exception:                                  # noqa: BLE001
                pass
        header = (f"# QRKSDock {__version__} | {self.ticket.id} | run {self.s.get('run_id', '')}\n"
                  "# Raw AutoDock Vina console output for each ligand follows, unmodified.\n")
        parts = [header]
        for r in results:
            raw = self._abs(r.log)
            if r.log and raw.exists():
                parts.append(f"\n# ===== {self.display_state(r)} (Vina seed {r.seed}) =====\n" + raw.read_text(encoding="utf-8"))
        (res_dir / "vina_output.log").write_text("".join(parts), encoding="utf-8")
        val_log = self.ticket.sub("work") / "validation" / "redock_vina.log"
        if val_log.exists():
            shutil.copy2(val_log, res_dir / "validation_vina_output.log")
        mpath = res_dir / "manifest.json"
        if mpath.exists():
            manifest.update_manifest(mpath, display_names=self.s.get("names", {}))

    def _write_manifest(self, params: DockParams, vina_ver: str) -> str:
        res_dir = self.ticket.sub("results")
        files = {"receptor_original": self._abs(self.s["receptor"]["source"]),
                 "receptor_pdbqt": self._abs(self.s["receptor"]["pdbqt"])}
        for r in self.results:
            files[f"poses_{r.state}"] = self._abs(r.out_pdbqt)
            files[f"vina_log_{r.state}"] = self._abs(r.log)
        for name in ("ligands_small_molecules.smi", "ligands_peptides.txt"):
            files[name] = self.ticket.sub("input") / name
        payload = {
            "ticket_id": self.ticket.id, "tier": self.ticket.tier, "test_ticket": self.ticket.is_test,
            "operator": self.actor, "operator_role": rules.role_of(self.actor),
            "environment": manifest.environment(vina_ver), "parameters": asdict(params),
            "vina_seeds": {r.state: r.seed for r in self.results},
            "box": self.s["box"],
            "receptor": {k: self.s["receptor"][k] for k in ("method", "ph", "chains_kept", "removed", "residue_states")},
            "stereo_policy": self.s.get("stereo_policy"), "ligands": self.s["prepared"],
            "validation": self.s.get("validation"), "validation_params": self.s.get("validation_params"),
            "results": self.s["results"], "file_sha256": manifest.hashes(files),
        }
        run_id = manifest.write_manifest(res_dir / "manifest.json", payload)
        self.s["run_id"] = run_id
        self.save()
        return run_id
