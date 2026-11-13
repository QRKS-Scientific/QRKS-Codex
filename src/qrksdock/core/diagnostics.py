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
    inter = (paths.asset("fonts") / "Inter-Regular.otf").exists() and (paths.asset("fonts") / "InterDisplay-Bold.otf").exists()
    add("Interface font", inter, "SF Pro (the macOS system font) on Mac; bundled Inter on other systems")
    report_fonts = all((paths.asset("fonts") / font).exists()
                       for font in ("PublicSans-Regular.ttf", "PublicSans-Medium.ttf", "PublicSans-Bold.ttf",
                                    "PublicSans-ExtraBold.ttf", "PublicSans-Italic.ttf", "PublicSans-BoldItalic.ttf"))
    add("Report font", report_fonts, "Bundled Public Sans Regular, Medium, Bold, ExtraBold, and Italic")
    try:
        from qrksdock.net.config import server_url
        from qrksdock.net.store import default_store
        st = default_store()
        add("Secure storage", st.persistent or sys.platform not in ("win32", "darwin"),
            f"{type(st).__name__} ({'OS keychain' if st.persistent else 'memory only: sign-in will not persist'})")
        add("QRKS server", True, server_url() or "not configured: local accounts (development mode)")
    except Exception as exc:                                                             # noqa: BLE001
        add("Secure storage", False, f"cannot check ({exc})")
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
    """Tiny end-to-end job in a temporary folder: receptor, ligand, Vina, results, PDF report."""
    from qrksdock.core.pipeline import DockParams, Project
    from qrksdock.core.report import generate_report
    from qrksdock.core.runs import Run

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

        def make_run():
            state["run"] = Run.create(tmp, "QC-000", "LEM")
            state["project"] = Project(state["run"], "LEM")
            return f"{state['run'].client} / {state['run'].code}"
        step("create run (client and QDOCK codes)", make_run)
        proj: Project = state["project"]
        step("receptor: pdb2pqr/PROPKA + Meeko", lambda: proj.prepare_receptor(
            paths.asset("selftest", "mini_receptor.pdb"), box_mode="blind")["box"].summary())
        step("ligands: Scrubber + Meeko", lambda: len(proj.prepare_ligands(
            "C1=CC=C(C(=C1)C(=O)C[C@@H](C(=O)O)N)N L-kynurenine\n", "GW dipeptide_GW\n")))
        step("docking: AutoDock Vina", lambda: [f"{r.state} {r.best_affinity:.2f}" for r in proj.run_docking(
            DockParams(exhaustiveness=2, num_modes=3, cpu=max(1, min(2, os.cpu_count() or 1))))])
        step("Vina log and exports", lambda: _check_exports(state["run"]))
        step("PDF report (draft)", lambda: generate_report(proj, "LEM").name)
        step("Qt loads (offscreen)", lambda: _qt_probe())
        step("login screen, accounts and fonts", lambda: _login_probe())
        step("secure storage and TLS certificates", lambda: _net_probe())
        ok = True
    except Exception:                                                                # noqa: BLE001
        ok = False
    return {"ok": ok, "seconds": round(time.time() - t0, 1), "steps": steps,
            "app_version": __version__, "platform": f"{platform.system()} {platform.machine()}"}


def _check_exports(run) -> str:
    res = run.sub("results")
    log = (res / "vina_output.log").read_text(encoding="utf-8")
    if "mode |   affinity" not in log or "random seed" not in log:
        raise RuntimeError("vina_output.log is missing Vina's result table or seed")
    if "Verbosity: 2" not in log or "Estimated Free Energy of Binding" not in log:
        raise RuntimeError("vina_output.log is not at verbosity 2 (no per-pose energy breakdown)")
    for name in ("results.csv", "poses.csv", "manifest.json"):
        if not (res / name).exists():
            raise RuntimeError(f"{name} was not written")
    return f"vina_output.log ({len(log)} bytes), results.csv, poses.csv, manifest.json"


def _qt_probe() -> str:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(sys.argv[:1])
    return f"QApplication created ({app.platformName()})"


def _login_probe() -> str:
    """Build the real window offscreen: proves the bundled accounts file, fonts and login screen all load."""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QApplication
    from qrksdock.gui import theme
    from qrksdock.gui.app import MainWindow
    app = QApplication.instance() or QApplication(sys.argv[:1])
    theme.apply(app)
    ini = Path(tempfile.mkdtemp(prefix="qrksdock_ui_")) / "s.ini"
    win = MainWindow(settings=QSettings(str(ini), QSettings.IniFormat))
    accounts = win.store.accounts()
    if len(accounts) != 6 or win.root_stack.currentIndex() != 0:
        raise RuntimeError(f"login screen shows {len(accounts)} accounts (expected 6)")
    body, _display = theme.load_fonts()
    return f"login screen with {len(accounts)} accounts; font: {body or 'system font'}"


def _net_probe() -> str:
    """Windows and macOS builds must have a real OS keychain; every build must carry the TLS certificate bundle."""
    import certifi
    from qrksdock.net.store import default_store
    store = default_store()
    store.set("selftest", "ok")
    if store.get("selftest") != "ok":
        raise RuntimeError("the secure store could not read back what it saved")
    store.delete("selftest")
    if sys.platform in ("win32", "darwin") and not store.persistent:
        raise RuntimeError("no operating-system keychain was found, so saved sign-ins would not survive a restart")
    if not os.path.exists(certifi.where()):
        raise RuntimeError("the TLS certificate bundle is missing, so the app could not verify the server")
    return f"{type(store).__name__} ({'persistent' if store.persistent else 'memory only'}); TLS certificates found"