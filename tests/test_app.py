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
