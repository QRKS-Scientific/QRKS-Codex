"""QRKSDock main window."""
from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QSettings, Qt, QTimer
from PySide6.QtGui import QAction, QGuiApplication, QIcon, QPixmap
from PySide6.QtWidgets import (QApplication, QDialog, QFileDialog, QFrame, QHBoxLayout, QLabel, QListWidget, QScrollArea,
                               QListWidgetItem, QMainWindow, QMessageBox, QPlainTextEdit, QProgressBar, QPushButton,
                               QStackedWidget, QVBoxLayout, QWidget)

from qrksdock import __version__, brand, paths
from qrksdock.core import diagnostics, rules
from qrksdock.core.accounts import AccountStore
from qrksdock.core.pipeline import Project
from qrksdock.core.runs import Run
from qrksdock.net.provider import RemoteAuthProvider
from qrksdock.net.services import NetServices
from qrksdock.net.sync import SyncResult
from qrksdock.gui import theme
from qrksdock.gui.avatars import avatar_pixmap
from qrksdock.gui.login import LoginPage
from qrksdock.gui.pages import DockingPage, LigandsPage, ReceptorPage, ProjectPage, ResultsPage, button, label, mono
from qrksdock.gui.workers import Worker

NAMES = ["Project", "Receptor", "Ligands", "Docking", "Results"]


class MainWindow(QMainWindow):
    def __init__(self, store=None, settings: QSettings | None = None, services: NetServices | None = None) -> None:
        super().__init__()
        self.settings = settings or QSettings("QRKS Scientific", "QRKSDock")
        self.run: Run | None = None
        self.project: Project | None = None
        self.busy = False
        self.worker: Worker | None = None
        # With a server configured, sign-in, run codes and activity go through it. Otherwise: local accounts (development).
        self.net: NetServices | None = services if services is not None else (None if store is not None else NetServices.create())
        self.store = store or (RemoteAuthProvider(self.net.session) if self.net else AccountStore())
        self._syncing = False
        self.sync_timer = QTimer(self)
        self.sync_timer.setInterval(30_000)
        self.sync_timer.timeout.connect(self._sync_now)
        self.user: dict | None = None
        self.operator = ""                           # initials of the signed-in lead, recorded in logs and manifests
        self.vina_path: str | None = (str(self.settings.value("vina_path", "")) or None)

        self.setWindowTitle(f"QRKSDock {__version__}  |  QRKS Scientific")
        self.setWindowIcon(QIcon(str(paths.asset("icons", "qrksdock_256.png"))))
        avail = QGuiApplication.primaryScreen().availableGeometry()          # fit the laptop's screen
        self.resize(int(min(1360, avail.width() * 0.94)), int(min(900, avail.height() * 0.94)))
        self.setMinimumSize(1000, 640)

        self.workspace = QWidget()
        self.workspace.setObjectName("canvas")
        root = self.workspace
        v = QVBoxLayout(root)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        v.addWidget(self._build_header())
        accent = QFrame()
        accent.setObjectName("accent")
        v.addWidget(accent)

        body = QHBoxLayout()
        body.setSpacing(0)
        self.rail = QListWidget()
        self.rail.setObjectName("rail")
        self.rail.setFixedWidth(184)
        self.rail.setFocusPolicy(Qt.NoFocus)
        for n in NAMES:
            self.rail.addItem(QListWidgetItem(theme.step_icon(False), n))
        self.stack = QStackedWidget()
        self.pages = [ProjectPage(self), ReceptorPage(self), LigandsPage(self), DockingPage(self), ResultsPage(self)]
        for p in self.pages:                                              # scroll instead of clipping on small screens
            sa = QScrollArea()
            sa.setWidgetResizable(True)
            sa.setFrameShape(QFrame.NoFrame)
            sa.setWidget(p)
            self.stack.addWidget(sa)
        self.rail.currentRowChanged.connect(self.stack.setCurrentIndex)
        self.rail.currentRowChanged.connect(lambda _i: self.refresh())
        body.addWidget(self.rail)
        body.addWidget(self.stack, 1)
        v.addLayout(body, 1)
        self.login = LoginPage(self.store, str(self.settings.value("last_user", "")))
        self.login.signedIn.connect(self.sign_in)
        self.root_stack = QStackedWidget()
        self.root_stack.addWidget(self.login)          # 0: sign in
        self.root_stack.addWidget(self.workspace)      # 1: the application
        self.setCentralWidget(self.root_stack)

        self.status_lbl = QLabel("Create or open a run to begin.")
        self.progress = QProgressBar()
        self.progress.setRange(0, 1000)
        self.progress.setFixedWidth(260)
        self.progress.hide()
        self.statusBar().addWidget(self.status_lbl, 1)
        self.statusBar().addPermanentWidget(self.progress)
        self._build_menu()
        self._set_signed_in(False)
        self.rail.setCurrentRow(0)
        self.refresh()
        if self.net:
            QTimer.singleShot(0, self._try_resume)           # let the sign-in screen draw first

    # ---- layout pieces -------------------------------------------------------------------------
    def _build_header(self) -> QWidget:
        h = QFrame()
        h.setObjectName("header")
        lay = QHBoxLayout(h)
        lay.setContentsMargins(22, 12, 22, 12)
        logo = QLabel()
        pm = QPixmap(str(paths.asset("logos", "qrksdock.png")))
        logo.setPixmap(pm.scaledToHeight(34, Qt.SmoothTransformation))
        lay.addWidget(logo)
        lay.addStretch(1)
        self.run_chip = label("No run open", "chip", False)
        lay.addWidget(self.run_chip)
        lay.addSpacing(14)
        self.sync_chip = label("", "chip", False)
        self.sync_chip.hide()
        lay.addWidget(self.sync_chip)
        lay.addSpacing(18)
        self.avatar_lbl = QLabel()
        self.avatar_lbl.setFixedSize(40, 40)
        lay.addWidget(self.avatar_lbl)
        who = QVBoxLayout()
        who.setSpacing(0)
        self.user_name = QLabel("")
        self.user_name.setObjectName("userName")
        self.user_role = label("", "muted", False)
        who.addWidget(self.user_name)
        who.addWidget(self.user_role)
        lay.addLayout(who)
        self.signout_btn = QPushButton("Sign out")
        self.signout_btn.setObjectName("ghost")
        self.signout_btn.setCursor(Qt.PointingHandCursor)
        self.signout_btn.clicked.connect(self.sign_out)
        lay.addWidget(self.signout_btn)
        return h

    def _build_menu(self) -> None:
        mb = self.menuBar()
        f = mb.addMenu("&File")
        a_open = QAction("Open run folder…", self)
        a_open.triggered.connect(self.pages[0]._open)
        a_out = QAction("Sign out", self)
        a_out.triggered.connect(self.sign_out)
        a_quit = QAction("Quit", self)
        a_quit.triggered.connect(self.close)
        f.addActions([a_open, a_out, a_quit])
        self._gated = [a_open, a_out]
        t = mb.addMenu("&Tools")
        a_vina = QAction("Choose Vina location…", self)
        a_vina.triggered.connect(self.choose_vina)
        t.addAction(a_vina)
        self._gated.append(a_vina)
        hp = mb.addMenu("&Help")
        a_chk = QAction("System check…", self)
        a_chk.triggered.connect(self.show_system_check)
        a_about = QAction("About QRKSDock", self)
        a_about.triggered.connect(self.show_about)
        hp.addActions([a_chk, a_about])

    # ---- state ----------------------------------------------------------------------------------------
    def goto(self, name: str) -> None:
        self.rail.setCurrentRow(NAMES.index(name))

    def set_run(self, run: Run) -> None:
        self.run = run
        self.project = Project(run, self.operator)
        self.status_lbl.setText(f"Run {run.code} ({run.client}) ready.")
        for p in self.pages:
            if isinstance(p, DockingPage):
                p.log.clear()
                p._touched = False
        self.refresh()

    def _set_signed_in(self, on: bool) -> None:
        for act in self._gated:
            act.setEnabled(on)

    def sign_in(self, initials: str) -> None:
        person = next((p for p in rules.roster() if p["initials"] == initials), None)
        if person is None:
            return
        self.user, self.operator = person, initials
        self.settings.setValue("last_user", initials)
        self.avatar_lbl.setPixmap(avatar_pixmap(initials, 40))
        self.user_name.setText(person["display_name"])
        self.user_role.setText(person["role"])
        if self.project:
            self.project.actor = initials
        self._set_signed_in(True)
        if self.net:
            Run.event_sink = self._on_run_event
            self.sync_timer.start()
            self.sync_chip.show()
            self._set_chip(SyncResult(pending=self.net.outbox.count(), online=not self.net.session.offline))
            QTimer.singleShot(0, self._sync_now)
        self.root_stack.setCurrentIndex(1)
        self.status_lbl.setText(f"Signed in as {person['display_name']} ({person['role']}). Create or open a run to begin.")
        self.refresh()

    def sign_out(self) -> None:
        if self.busy:
            QMessageBox.information(self, "Please wait", "A job is still running. Wait for it to finish or cancel it first.")
            return
        self.user, self.operator = None, ""
        self.run, self.project = None, None
        Run.event_sink = None
        self.sync_timer.stop()
        self.sync_chip.hide()
        self.store.sign_out()
        self._set_signed_in(False)
        self.login.reset()
        self.root_stack.setCurrentIndex(0)
        self.rail.setCurrentRow(0)
        self.refresh()

    # ---- server: saved session, event sync, status chip ------------------------------------------------------------------------
    def _try_resume(self) -> None:
        """Silent sign-in from the saved session (with the 7-day offline grace), without freezing the window."""
        self.status_lbl.setText("Checking your saved sign-in…")
        self._resume_worker = Worker(lambda log, progress, cancel: self.store.resume())
        self._resume_worker.done.connect(self._resume_done)
        self._resume_worker.failed.connect(lambda _m: self.status_lbl.setText("Sign in to begin."))
        self._resume_worker.start()

    def _resume_done(self, initials) -> None:
        if initials:
            self.sign_in(initials)
        else:
            self.status_lbl.setText("Sign in to begin.")

    def _on_run_event(self, run: Run, entry: dict) -> None:
        if self.net:
            self.net.outbox.enqueue(run.code, run.client, entry["type"], entry.get("data", {}), entry["utc"])

    def _sync_now(self) -> None:
        if not self.net or not self.user or self._syncing:
            return
        self._syncing = True
        self._sync_worker = Worker(lambda log, progress, cancel: self.net.sync.flush())
        self._sync_worker.done.connect(self._sync_done)
        self._sync_worker.failed.connect(lambda _m: setattr(self, "_syncing", False))
        self._sync_worker.start()

    def _sync_done(self, result: SyncResult) -> None:
        self._syncing = False
        if self.net and self.net.session.session_lost and self.user:
            QMessageBox.information(self, "Signed out", "The server ended your session. Sign in again.")
            self.net.session.session_lost = False
            self.sign_out()
            return
        self._set_chip(result)
        if self.net and result.online:
            waiting = self.net.outbox.count()
            # Events that arrived while that sync was running (more waiting than it saw), or progress with more to send:
            # go again now instead of waiting for the 30-second timer. No progress and nothing new means stop (no spinning).
            if waiting > result.pending or (result.sent > 0 and waiting > 0):
                QTimer.singleShot(200, self._sync_now)

    def _set_chip(self, r: SyncResult) -> None:
        if r.online:
            self.sync_chip.setText("Online" + (f"  |  {r.pending} waiting" if r.pending else ""))
            name = "chipOk"
        else:
            self.sync_chip.setText(f"Offline  |  {r.pending} waiting")
            name = "chip"
        self.sync_chip.setObjectName(name)
        self.sync_chip.style().unpolish(self.sync_chip)
        self.sync_chip.style().polish(self.sync_chip)

    def closeEvent(self, event) -> None:
        Run.event_sink = None
        self.sync_timer.stop()
        super().closeEvent(event)

    def require_run(self) -> bool:
        if self.busy:
            QMessageBox.information(self, "Please wait", "A job is still running.")
            return False
        if not self.run or not self.project:
            QMessageBox.information(self, "No run", "Create or open a run first.")
            self.goto("Project")
            return False
        return True

    def refresh(self) -> None:
        t, p = self.run, self.project
        self.run_chip.setText(t.label if t else "No run open")
        done = [bool(t), bool(p and p.receptor_ready), bool(p and p.ligands_ready), bool(p and p.results),
                bool(t and any(t.sub("reports").glob("*.pdf")))]
        for i, d in enumerate(done):
            self.rail.item(i).setIcon(theme.step_icon(d))
        self.pages[self.stack.currentIndex()].refresh()
        for pg in self.pages:
            if isinstance(pg, DockingPage):
                pg.set_busy(self.busy)

    # ---- jobs ----------------------------------------------------------------------------------------------
    def run_job(self, fn, on_done, message: str, log_to=None, cancellable: bool = False) -> None:
        if self.busy:
            return
        self.busy = True
        self.worker = Worker(fn, self)
        self.status_lbl.setText(message)
        self.progress.setValue(0)
        self.progress.show()
        sink = log_to or (lambda s: self.status_lbl.setText(s.strip()))
        self.worker.log.connect(sink)
        self.worker.progress.connect(lambda f, m: (self.progress.setValue(int(f * 1000)), self.status_lbl.setText(m)))

        def finished():
            self.busy = False
            self.progress.hide()
            self.refresh()
            self._sync_now()

        def ok(res):
            try:
                on_done(res)
            finally:
                self.status_lbl.setText("Done.")

        def bad(msg):
            self.status_lbl.setText("Stopped: see message.")
            if log_to:
                log_to(f"ERROR: {msg}")
            QMessageBox.warning(self, "QRKSDock", msg)

        def cancelled():
            self.status_lbl.setText("Cancelled.")
            if log_to:
                log_to("Cancelled by the operator.")

        self.worker.done.connect(ok)
        self.worker.failed.connect(bad)
        self.worker.cancelled.connect(cancelled)
        self.worker.finished.connect(finished)
        self.refresh()
        self.worker.start()

    def cancel_job(self) -> None:
        if self.worker and self.busy:
            self.worker.cancel_event.set()
            self.status_lbl.setText("Cancelling…")

    # ---- menu actions ----------------------------------------------------------------------------------------
    def choose_vina(self) -> None:
        f, _ = QFileDialog.getOpenFileName(self, "Locate the AutoDock Vina executable")
        if f:
            self.vina_path = f
            self.settings.setValue("vina_path", f)
            self.show_system_check()

    def show_system_check(self) -> None:
        text = diagnostics.format_check(diagnostics.system_check(self.vina_path))
        dlg = QDialog(self)
        dlg.setWindowTitle("System check")
        dlg.resize(780, 420)
        lay = QVBoxLayout(dlg)
        lay.addWidget(label("If anything shows FAIL, copy this text and send it to the Technical Lead.", "muted"))
        box = QPlainTextEdit(text)
        box.setReadOnly(True)
        mono(box)
        lay.addWidget(box, 1)
        row = QHBoxLayout()
        cp = button("Copy to clipboard", True)
        cp.clicked.connect(lambda: QGuiApplication.clipboard().setText(text))
        cl = button("Close")
        cl.clicked.connect(dlg.accept)
        row.addStretch(1)
        row.addWidget(cp)
        row.addWidget(cl)
        lay.addLayout(row)
        dlg.exec()

    def show_about(self) -> None:
        QMessageBox.about(
            self, "About QRKSDock",
            f"<b>QRKSDock Desktop {__version__}</b><br>QRKS Scientific<br><i>{brand.TAGLINE}</i><br><br>"
            "Docking engine: AutoDock Vina. Preparation: Meeko, Scrubber, pdb2pqr, PROPKA, RDKit.<br>"
            "See THIRD_PARTY_NOTICES.md for licenses.")


def run_gui() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("QRKSDock")
    app.setOrganizationName("QRKS Scientific")
    theme.apply(app)
    win = MainWindow()
    win.show()
    return app.exec()
