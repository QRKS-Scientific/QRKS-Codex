import os

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def test_selftest_passes(vina_exe):
    from qrksdock.core import diagnostics
    result = diagnostics.selftest(log=lambda s: None)
    assert result["ok"], result


def _win(tmp_path, store=None):
    """A window whose accounts and settings live in the test's own temporary folder."""
    from PySide6.QtCore import QSettings
    from qrksdock.gui.app import MainWindow
    return MainWindow(store or _store(tmp_path), QSettings(str(tmp_path / "qt.ini"), QSettings.IniFormat))


def _app():
    from PySide6.QtWidgets import QApplication
    from qrksdock.gui import theme
    app = QApplication.instance() or QApplication([])
    theme.apply(app)
    return app


def test_window_builds_and_creates_a_run(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    from qrksdock.gui.app import NAMES, MainWindow
    _app()
    shown = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: shown.append(a[2]))
    win = _win(tmp_path)
    assert win.root_stack.currentIndex() == 0                                    # the app starts on the login screen
    win.sign_in("LEM")
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
    assert not hasattr(win, "op_combo")                                          # the old "Signed in as" dropdown is gone


def test_report_type_choice_exists(tmp_path):
    from qrksdock.gui.app import MainWindow
    _app()
    rp = _win(tmp_path).pages[4]
    assert [rp.report_type.itemText(i) for i in range(rp.report_type.count())] == ["Draft (watermarked)", "Final (no watermark)"]
    assert rp.report_type.currentIndex() == 0                                    # Draft is the safe default


def test_docking_page_has_no_seed_and_top10_defaults(tmp_path):
    from PySide6.QtWidgets import QApplication
    from qrksdock.gui import theme
    from qrksdock.gui.app import MainWindow
    app = QApplication.instance() or QApplication([])
    theme.apply(app)
    dp = _win(tmp_path).pages[3]
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
    theme.apply(app)
    win = _win(tmp_path)
    win.sign_in("LEM")
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


# ---- login screen -----------------------------------------------------------------------------------------------
def _store(tmp_path):
    import json
    from qrksdock.core import accounts as acc
    shipped = tmp_path / "test_accounts.json"
    shipped.write_text(json.dumps({"version": 1, "accounts": {
        p["initials"]: acc.hash_password("TEMP-" + p["initials"] + "-0001", iterations=1000) for p in __import__("qrksdock.core.rules", fromlist=["x"]).roster()}}))
    return acc.AccountStore(shipped_file=shipped, local_dir=tmp_path / "local")


def test_login_screen_lists_six_accounts_and_has_no_signup(tmp_path):
    from PySide6.QtWidgets import QPushButton
    _app()
    win = _win(tmp_path)
    assert win.root_stack.currentIndex() == 0
    assert [a["initials"] for a in win.store.accounts()] == ["LEM", "JER", "LPA", "JCG", "JML", "ERD"]
    texts = " ".join(b.text().lower() for b in win.login.findChildren(QPushButton))
    assert "sign in" in texts and "continue" in texts
    assert "register" not in texts and "create account" not in texts and "sign up" not in texts
    assert not win.login.next_btn.isEnabled() and not win.login.go.isEnabled()
    assert not any(a.isEnabled() for a in win._gated)                            # menus that need a user are off


def test_full_sign_in_with_forced_password_change_and_sign_out(tmp_path, monkeypatch):
    from qrksdock.gui.login import ChangePasswordDialog
    _app()
    win = _win(tmp_path)

    def fake_exec(self):                                                         # stands in for the person typing a new password
        self.new.setText("river-Stone-84-lamp")
        self.again.setText("river-Stone-84-lamp")
        self._save()
        return self.result()
    monkeypatch.setattr(ChangePasswordDialog, "exec", fake_exec)
    win.login.email.setText("jer@qrks.com")
    win.login._advance_to_password()
    assert not win.login.auth_step.isHidden() and win.login.name_lbl.text() == "John E. Rico, RCh."
    win.login.password.setText("TEMP-JER-0001")
    win.login._submit()
    assert win.root_stack.currentIndex() == 1 and win.operator == "JER"
    assert win.user_name.text() == "John E. Rico, RCh." and win.user_role.text() == "Operations Lead"
    assert win.store.authenticate("jer@qrks.com", "river-Stone-84-lamp").ok
    win.sign_out()
    assert win.root_stack.currentIndex() == 0 and win.operator == "" and win.run is None
    assert win.login.auth_step.isHidden() and not win.login.email.text() and not win.login.password.text()


def test_wrong_password_shows_attempts_then_locks_the_button(tmp_path):
    _app()
    win = _win(tmp_path)
    login = win.login
    login.email.setText("lem@qrks.com")
    login._advance_to_password()
    login.password.setText("wrong")
    login._submit()
    assert not login.msg.isHidden() and "4 attempts left" in login.msg.text() and win.root_stack.currentIndex() == 0
    for _ in range(4):
        login.password.setText("wrong")
        login._submit()
    assert "locked" in login.msg.text() and not login.go.isEnabled()
    login.password.setText("TEMP-LEM-0001")
    login._submit()
    assert win.root_stack.currentIndex() == 0                                    # still refused while locked


def test_sign_out_is_blocked_while_a_job_runs(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    _app()
    win = _win(tmp_path)
    win.sign_in("LEM")
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    win.busy = True
    win.sign_out()
    assert win.root_stack.currentIndex() == 1 and win.operator == "LEM"


def test_missing_accounts_file_is_reported_not_silent(tmp_path):
    from qrksdock.core import accounts as acc
    _app()
    empty = acc.AccountStore(shipped_file=tmp_path / "nothing.json", local_dir=tmp_path / "local")
    win = _win(tmp_path, empty)
    assert not win.store.accounts() and not win.login.msg.isHidden() and "No accounts were found" in win.login.msg.text()


def test_packaging_spec_bundles_accounts_and_rules():
    """Regression: v0.4.0's first frozen build shipped without accounts.json, so nobody could sign in."""
    from qrksdock import paths
    spec = (paths.base_dir() / "packaging" / "qrksdock.spec").read_text()
    assert 'src" / "qrksdock" / "data"), "qrksdock_data"' in spec          # the whole data folder, not single files
    assert (paths.base_dir() / "src" / "qrksdock" / "data" / "accounts.json").exists()
    assert (paths.base_dir() / "src" / "qrksdock" / "data" / "rules.json").exists()