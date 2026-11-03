"""System check (used by Help > System check, `qrksdock doctor`) and the headless self-test."""
from __future__ import annotations

import os
import platform
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

from qrksdock import __version__, paths
from qrksdock.core import manifest, rules, vina_runner


def system_check(vina_path: str | None = None) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []

    def add(name: str, ok: bool, detail: str) -> None:
        items.append({"name": name, "ok": ok, "detail": detail})

    add("QRKSDock", True, f"{__version__} (rules {rules.load()['rules_version']}), "
                          f"{'installed app' if paths.is_frozen() else 'running from source'}")
    add("Computer", True, f"{platform.system()} {platform.release()} {platform.machine()}, {os.cpu_count()} CPU cores, Python {platform.python_version()}")
    exe = vina_runner.find_vina(vina_path)
    if exe is None:
        add("AutoDock Vina", False, "Not found. Run scripts/fetch_vina.py, or set the location in Settings.")
    else:
        try:
            add("AutoDock Vina", True, f"{vina_runner.vina_version(exe)} at {exe}")
        except vina_runner.VinaError as exc:
            add("AutoDock Vina", False, str(exc))
    for label, dist, mod in (("RDKit", "rdkit", "rdkit"), ("Meeko", "meeko", "meeko"), ("Scrubber", "molscrub", "molscrub"),
                             ("pdb2pqr", "pdb2pqr", "pdb2pqr"), ("PROPKA", "propka", "propka"), ("ReportLab", "reportlab", "reportlab")):
        try:
            __import__(mod)
            add(label, True, manifest._pkg_version(dist, mod))
        except Exception as exc:                                                     # noqa: BLE001
            add(label, False, f"cannot import ({exc})")
    try:
        import PySide6
        add("Qt (PySide6)", True, PySide6.__version__)
    except Exception as exc:                                                         # noqa: BLE001
        add("Qt (PySide6)", False, f"cannot import ({exc})")
    add("Brand fonts", (paths.asset("fonts") / "Montserrat-Regular.ttf").exists(), "Montserrat bundled")
    try:
        probe = paths.user_data_dir() / ".write_test"
        probe.write_text("ok")
        probe.unlink()
        add("Settings folder", True, str(paths.user_data_dir()))
    except OSError as exc:
        add("Settings folder", False, str(exc))
    return items


def format_check(items: list[dict[str, Any]]) -> str:
    return "\n".join(f"[{'OK' if i['ok'] else 'FAIL'}] {i['name']}: {i['detail']}" for i in items)


def selftest(log=print) -> dict[str, Any]:
    """Tiny end-to-end run on a test ticket: receptor, ligand, Vina, results, PDF report."""
    from qrksdock.core.pipeline import DockParams, Project
    from qrksdock.core.report import generate_report
    from qrksdock.core.tickets import Ticket

    t0 = time.time()
    steps: list[dict[str, Any]] = []

    def step(name: str, fn):
        t = time.time()
        try:
            detail = fn()
            steps.append({"step": name, "ok": True, "detail": str(detail), "seconds": round(time.time() - t, 1)})
        except Exception as exc:                                                     # noqa: BLE001
            steps.append({"step": name, "ok": False, "detail": f"{type(exc).__name__}: {exc}", "seconds": round(time.time() - t, 1)})
            raise
        log(f"  ok  {name}")

    state: dict[str, Any] = {}
    try:
        step("system check", lambda: (lambda c: "all components found" if all(i["ok"] for i in c) else
                                      (_ for _ in ()).throw(RuntimeError(format_check([i for i in c if not i["ok"]]))))(system_check()))
        tmp = Path(tempfile.mkdtemp(prefix="qrksdock_selftest_"))

        def make_ticket():
            state["ticket"] = Ticket.create(tmp, "Hadron", "LEM", test=True)
            state["project"] = Project(state["ticket"], "LEM")
            return state["ticket"].id
        step("create test ticket", make_ticket)
        proj: Project = state["project"]
        step("receptor: pdb2pqr/PROPKA + Meeko", lambda: proj.prepare_receptor(
            paths.asset("selftest", "mini_receptor.pdb"), box_mode="blind")["box"].summary())
        step("ligands: Scrubber + Meeko", lambda: len(proj.prepare_ligands(
            "C1=CC=C(C(=C1)C(=O)C[C@@H](C(=O)O)N)N L-kynurenine\n", "GW dipeptide_GW\n")))
        step("docking: AutoDock Vina", lambda: [f"{r.state} {r.best_affinity:.2f}" for r in proj.run_docking(
            DockParams(exhaustiveness=2, num_modes=3, cpu=max(1, min(2, os.cpu_count() or 1))))])
        step("PDF report", lambda: generate_report(proj, "LEM").name)
        step("Qt loads (offscreen)", lambda: _qt_probe())
        ok = True
    except Exception:                                                                # noqa: BLE001
        ok = False
    return {"ok": ok, "seconds": round(time.time() - t0, 1), "steps": steps,
            "app_version": __version__, "platform": f"{platform.system()} {platform.machine()}"}


def _qt_probe() -> str:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(sys.argv[:1])
    return f"QApplication created ({app.platformName()})"
