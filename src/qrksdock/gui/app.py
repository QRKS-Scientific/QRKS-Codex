"""QRKSDock main window."""
from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QAction, QGuiApplication, QIcon, QPixmap
from PySide6.QtWidgets import (QApplication, QComboBox, QDialog, QFileDialog, QFrame, QHBoxLayout, QLabel, QListWidget,
                               QListWidgetItem, QMainWindow, QMessageBox, QPlainTextEdit, QProgressBar, QPushButton,
                               QStackedWidget, QVBoxLayout, QWidget)

from qrksdock import __version__, brand, paths
from qrksdock.core import diagnostics, rules
from qrksdock.core.pipeline import Project
from qrksdock.core.tickets import Ticket
from qrksdock.gui import theme
from qrksdock.gui.pages import DockingPage, LigandsPage, ReceptorPage, ResultsPage, TicketPage, button, label, mono
from qrksdock.gui.workers import Worker

NAMES = ["Ticket", "Receptor", "Ligands", "Docking", "Results"]


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.settings = QSettings("QRKS Scientific", "QRKSDock")
        self.ticket: Ticket | None = None
        self.project: Project | None = None
        self.busy = False
        self.worker: Worker | None = None
        saved_op = str(self.settings.value("operator", "LEM"))
        self.operator = saved_op if saved_op in [p["initials"] for p in rules.roster()] else rules.roster()[0]["initials"]
        self.vina_path: str | None = (str(self.settings.value("vina_path", "")) or None)

        self.setWindowTitle(f"QRKSDock {__version__}  |  QRKS Scientific")
        self.setWindowIcon(QIcon(str(paths.asset("icons", "qrksdock_256.png"))))
        self.resize(1120, 760)
        self.setMinimumSize(940, 640)

        root = QWidget()
        root.setObjectName("canvas")
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
        self.pages = [TicketPage(self), ReceptorPage(self), LigandsPage(self), DockingPage(self), ResultsPage(self)]
        for p in self.pages:
            self.stack.addWidget(p)
        self.rail.currentRowChanged.connect(self.stack.setCurrentIndex)
        self.rail.currentRowChanged.connect(lambda _i: self.refresh())
        body.addWidget(self.rail)
        body.addWidget(self.stack, 1)
        v.addLayout(body, 1)
        self.setCentralWidget(root)

        self.status_lbl = QLabel("Open or create a ticket to begin.")
        self.progress = QProgressBar()
        self.progress.setRange(0, 1000)
        self.progress.setFixedWidth(260)
        self.progress.hide()
        self.statusBar().addWidget(self.status_lbl, 1)
        self.statusBar().addPermanentWidget(self.progress)
        self._build_menu()
        self.rail.setCurrentRow(0)
        self.refresh()

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
        self.ticket_chip = label("No ticket open", "chip", False)
        lay.addWidget(self.ticket_chip)
        lay.addSpacing(14)
        lay.addWidget(label("Signed in as", "muted", False))
        self.op_combo = QComboBox()
        for p in rules.roster():
            self.op_combo.addItem(f"{p['initials']}  {p['role']}", p["initials"])
        self.op_combo.setCurrentIndex(max(0, self.op_combo.findData(self.operator)))
        self.op_combo.currentIndexChanged.connect(self._operator_changed)
        lay.addWidget(self.op_combo)
        return h

    def _build_menu(self) -> None:
        mb = self.menuBar()
        f = mb.addMenu("&File")
        a_open = QAction("Open ticket folder…", self)
        a_open.triggered.connect(self.pages[0]._open)
        a_quit = QAction("Quit", self)
        a_quit.triggered.connect(self.close)
        f.addActions([a_open, a_quit])
        t = mb.addMenu("&Tools")
        a_vina = QAction("Choose Vina location…", self)
        a_vina.triggered.connect(self.choose_vina)
        t.addAction(a_vina)
        hp = mb.addMenu("&Help")
        a_chk = QAction("System check…", self)
        a_chk.triggered.connect(self.show_system_check)
        a_about = QAction("About QRKSDock", self)
        a_about.triggered.connect(self.show_about)
        hp.addActions([a_chk, a_about])

    # ---- state ----------------------------------------------------------------------------------------
    def goto(self, name: str) -> None:
        self.rail.setCurrentRow(NAMES.index(name))

    def set_ticket(self, ticket: Ticket) -> None:
        self.ticket = ticket
        self.project = Project(ticket, self.operator)
        self.status_lbl.setText(f"Ticket {ticket.id} ready.")
        for p in self.pages:
            if isinstance(p, DockingPage):
                p.log.clear()
                p._touched = False
        self.refresh()

    def _operator_changed(self) -> None:
        self.operator = self.op_combo.currentData()
        self.settings.setValue("operator", self.operator)
        if self.project:
            self.project.actor = self.operator
        self.refresh()

    def require_ticket(self) -> bool:
        if self.busy:
            QMessageBox.information(self, "Please wait", "A job is still running.")
            return False
        if not self.ticket or not self.project:
            QMessageBox.information(self, "No ticket", "Open or create a ticket first.")
            self.goto("Ticket")
            return False
        return True

    def refresh(self) -> None:
        t, p = self.ticket, self.project
        self.ticket_chip.setText(f"{t.id}  |  {t.tier}" if t else "No ticket open")
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
    family = theme.load_fonts()
    app.setFont(theme.base_font(family))
    app.setStyleSheet(theme.stylesheet(family))
    win = MainWindow()
    win.show()
    return app.exec()
