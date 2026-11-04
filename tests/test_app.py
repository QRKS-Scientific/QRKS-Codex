import os

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def test_selftest_passes(vina_exe):
    from qrksdock.core import diagnostics
    result = diagnostics.selftest(log=lambda s: None)
    assert result["ok"], result


def test_window_builds_and_role_gating(tmp_path):
    from PySide6.QtWidgets import QApplication
    from qrksdock.gui import theme
    from qrksdock.gui.app import NAMES, MainWindow
    app = QApplication.instance() or QApplication([])
    app.setStyleSheet(theme.stylesheet(theme.load_fonts()))
    win = MainWindow()
    assert [win.rail.item(i).text() for i in range(win.rail.count())] == NAMES
    win.operator = "JML"
    win.pages[0].root_edit.setText(str(tmp_path))
    win.pages[0]._new(False)                                    # Documentations Lead may create tickets
    assert win.ticket and not win.ticket.is_test
    win.operator = "LEM"
    win.project.actor = "LEM"
    win.refresh()
    assert win.require_ticket()
    assert not win.pages[3].run_btn.isEnabled()                 # nothing prepared yet


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
    from qrksdock.core.tickets import Ticket
    from qrksdock.gui import theme
    from qrksdock.gui.app import MainWindow
    app = QApplication.instance() or QApplication([])
    app.setStyleSheet(theme.stylesheet(theme.load_fonts()))
    win = MainWindow()
    win.set_ticket(Ticket.create(tmp_path, "Hadron", "LEM", test=True))
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
