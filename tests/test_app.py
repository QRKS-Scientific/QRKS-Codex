import os

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def test_selftest_passes(vina_exe):
    from qrksdock.core import diagnostics
    result = diagnostics.selftest(log=lambda s: None)
    assert result["ok"], result


def _app():
    from PySide6.QtWidgets import QApplication
    from qrksdock.gui import theme
    app = QApplication.instance() or QApplication([])
    app.setStyleSheet(theme.stylesheet(theme.load_fonts()))
    return app


def test_window_builds_and_creates_a_run(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    from qrksdock.gui.app import NAMES, MainWindow
    _app()
    shown = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: shown.append(a[2]))
    win = MainWindow()
    assert [win.rail.item(i).text() for i in range(win.rail.count())] == NAMES and NAMES[0] == "Project"
    page = win.pages[0]
    page.root_edit.setText(str(tmp_path))
    page.client_edit.setText("not a code")
    page._new()
    assert win.run is None and shown and "client code" in shown[0]               # bad client code: warning, no run
    page.client_edit.setText("qc-1")
    page._new()
    assert win.run and win.run.client == "QC-001" and win.run.path.parent.name == "QC-001"
    page.refresh()
    assert page.runs.rowCount() == 1 and page.runs.item(0, 1).text() == win.run.code
    assert win.run_chip.text() == win.run.label and not win.pages[3].run_btn.isEnabled()
    assert not hasattr(win, "op_combo") or win.op_combo.count() == 6              # operator dropdown stays until the login phase


def test_report_type_choice_exists(tmp_path):
    from qrksdock.gui.app import MainWindow
    _app()
    rp = MainWindow().pages[4]
    assert [rp.report_type.itemText(i) for i in range(rp.report_type.count())] == ["Draft (watermarked)", "Final (no watermark)"]
    assert rp.report_type.currentIndex() == 0                                    # Draft is the safe default


def test_docking_page_has_no_seed_and_top10_defaults(tmp_path):
    from PySide6.QtWidgets import QApplication
    from qrksdock.gui import theme
    from qrksdock.gui.app import MainWindow
    app = QApplication.instance() or QApplication([])
    app.setStyleSheet(theme.stylesheet(theme.load_fonts()))
    dp = MainWindow().pages[3]
    assert not hasattr(dp, "seed")
    assert dp.poses.value() == 10 and dp.erange.value() == 10
    assert dp.params().seed is None


def test_results_table_rename_by_editing_a_cell(tmp_path, vina_exe):
    from PySide6.QtWidgets import QApplication
    from qrksdock import paths
    from qrksdock.core.pipeline import DockParams
    from qrksdock.core.runs import Run
    from qrksdock.gui import theme
    from qrksdock.gui.app import MainWindow
    app = QApplication.instance() or QApplication([])
    app.setStyleSheet(theme.stylesheet(theme.load_fonts()))
    win = MainWindow()
    win.set_run(Run.create(tmp_path, "QC-001", "LEM"))
    win.project.prepare_receptor(paths.asset("selftest", "mini_receptor.pdb"), box_mode="blind")
    win.project.prepare_ligands("CCO ethanol\nCCN ethylamine\n", "")
    win.project.run_docking(DockParams(exhaustiveness=2, cpu=1))
    win.refresh()
    rp = win.pages[4]
    win.goto("Results")
    assert rp.table.rowCount() == 2 and rp.pose_table.rowCount() >= 5       # pose detail shows the selected ligand's poses
    cell = rp.table.item(0, 1)
    old = cell.data(0x100)                                                    # Qt.UserRole: the ligand's internal id
    cell.setText("My renamed ligand")                                         # same as the user double-clicking and typing
    app.processEvents()
    assert win.project.display_ligand(old) == "My_renamed_ligand"
    assert any(rp.table.item(r, 1).text() == "My_renamed_ligand" for r in range(rp.table.rowCount()))
