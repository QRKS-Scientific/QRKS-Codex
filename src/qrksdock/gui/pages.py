"""The five workflow pages. Each page reads and writes through `win.project`; no science here."""
from __future__ import annotations

import os
import shutil
from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QColor, QDesktopServices, QFontDatabase
from PySide6.QtWidgets import (QAbstractItemView, QButtonGroup, QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog, QFormLayout,
                               QFrame, QGridLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMessageBox,
                               QPlainTextEdit, QProgressBar, QPushButton, QRadioButton, QSpinBox, QTableWidget,
                               QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget)

from qrksdock import brand
from qrksdock.core import box as boxmod
from qrksdock.core import ligands, receptor, rules, vina_runner
from qrksdock.core.pipeline import DockParams, Project
from qrksdock.core.report import generate_report
from qrksdock.core.tickets import PermissionDenied, Ticket, TicketError

P = brand.ACTIVE


def open_path(path: Path) -> None:
    QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))


def label(text: str, role: str | None = None, wrap: bool = True) -> QLabel:
    lb = QLabel(text)
    if role:
        lb.setObjectName(role)
    lb.setWordWrap(wrap)
    lb.setTextInteractionFlags(Qt.TextSelectableByMouse)
    return lb


def button(text: str, secondary: bool = False) -> QPushButton:
    b = QPushButton(text)
    if secondary:
        b.setObjectName("secondary")
    b.setCursor(Qt.PointingHandCursor)
    return b


def mono(widget) -> None:
    widget.setFont(QFontDatabase.systemFont(QFontDatabase.FixedFont))


def fill_table(table: QTableWidget, headers: list[str], rows: list[list], row_colors: list[str | None] | None = None,
               stretch_col: int | None = None, editable_cols: set[int] | None = None,
               row_ids: list[str] | None = None) -> None:
    table.setSortingEnabled(False)
    table.clear()
    table.setColumnCount(len(headers))
    table.setHorizontalHeaderLabels(headers)
    table.setRowCount(len(rows))
    for r, row in enumerate(rows):
        for c, val in enumerate(row):
            it = QTableWidgetItem(str(val))
            if editable_cols and c in editable_cols:
                it.setToolTip("Double-click to rename")
                if row_ids:
                    it.setData(Qt.UserRole, row_ids[r])
            else:
                it.setFlags(it.flags() & ~Qt.ItemIsEditable)
            if row_colors and row_colors[r]:
                it.setBackground(QColor(row_colors[r]))
            table.setItem(r, c, it)
    table.verticalHeader().setVisible(False)
    table.setEditTriggers(QAbstractItemView.DoubleClicked if editable_cols else QAbstractItemView.NoEditTriggers)
    table.setSelectionBehavior(QAbstractItemView.SelectRows)
    table.setAlternatingRowColors(not row_colors)
    hh = table.horizontalHeader()
    hh.setSectionResizeMode(QHeaderView.ResizeToContents)
    if stretch_col is not None:
        hh.setSectionResizeMode(stretch_col, QHeaderView.Stretch)
        table.setWordWrap(True)
        table.resizeRowsToContents()


class Page(QWidget):
    title = ""
    blurb = ""

    def __init__(self, win):
        super().__init__()
        self.win = win
        self.setObjectName("canvas")
        self.setMinimumWidth(980)                      # below this the page scrolls sideways instead of squashing columns
        outer = QVBoxLayout(self)
        outer.setContentsMargins(32, 26, 32, 20)
        outer.setSpacing(12)
        outer.addWidget(label(self.title, "h1"))
        if self.blurb:
            outer.addWidget(label(self.blurb, "muted"))
        self.body = QVBoxLayout()
        self.body.setSpacing(12)
        outer.addLayout(self.body, 1)

    def refresh(self) -> None:
        pass


# ---------------------------------------------------------------------------------------------------
class TicketPage(Page):
    title = "Ticket"
    blurb = "Every docking job lives in a ticket folder, normally inside the client directory on Google Drive."

    def __init__(self, win):
        super().__init__(win)
        row = QHBoxLayout()
        self.root_edit = QLineEdit(win.settings.value("tickets_root", str(Path.home() / "Documents" / "QRKS Tickets")))
        b = button("Browse…", True)
        b.clicked.connect(self._browse_root)
        row.addWidget(label("Tickets folder", "h2", False))
        row.addWidget(self.root_edit, 1)
        row.addWidget(b)
        self.body.addLayout(row)

        row2 = QHBoxLayout()
        self.tier_combo = QComboBox()
        self.tier_combo.addItems(rules.tiers())
        self.client_edit = QLineEdit()
        self.client_edit.setPlaceholderText("Client reference (code or initials, no personal details)")
        self.open_btn = button("Open ticket folder…")
        self.new_btn = button("New ticket", True)
        self.test_btn = button("New test ticket", True)
        self.open_btn.clicked.connect(self._open)
        self.new_btn.clicked.connect(lambda: self._new(False))
        self.test_btn.clicked.connect(lambda: self._new(True))
        for w in (self.open_btn, label("or create:", "muted", False), self.tier_combo, self.client_edit, self.new_btn, self.test_btn):
            row2.addWidget(w, 1 if w is self.client_edit else 0)
        self.body.addLayout(row2)

        self.info = label("No ticket open.", "summary")
        self.body.addWidget(self.info)

        self.flag_grid = QGridLayout()
        self.flag_grid.setHorizontalSpacing(14)
        gw = QWidget()
        gw.setLayout(self.flag_grid)
        self.body.addWidget(label("Ticket status", "h2"))
        self.body.addWidget(gw)
        self.body.addWidget(label("Activity", "h2"))
        self.events = QPlainTextEdit()
        self.events.setReadOnly(True)
        mono(self.events)
        self.body.addWidget(self.events, 1)

    def _browse_root(self):
        d = QFileDialog.getExistingDirectory(self, "Choose the tickets folder", self.root_edit.text())
        if d:
            self.root_edit.setText(d)
            self.win.settings.setValue("tickets_root", d)

    def _open(self):
        d = QFileDialog.getExistingDirectory(self, "Open a ticket folder", self.root_edit.text())
        if d:
            try:
                self.win.set_ticket(Ticket.open(Path(d)))
            except TicketError as exc:
                QMessageBox.warning(self, "Open ticket", str(exc))

    def _new(self, test: bool):
        root = Path(self.root_edit.text())
        self.win.settings.setValue("tickets_root", str(root))
        try:
            self.win.set_ticket(Ticket.create(root, self.tier_combo.currentText(), self.win.operator,
                                              self.client_edit.text().strip(), test=test))
        except (TicketError, PermissionDenied, OSError) as exc:
            QMessageBox.warning(self, "New ticket", str(exc))

    def _toggle_flag(self, flag: str, value: bool):
        try:
            self.win.ticket.set_flag(self.win.operator, flag, value)
        except PermissionDenied as exc:
            QMessageBox.warning(self, "Not allowed", str(exc))
        self.win.refresh()

    def refresh(self):
        t = self.win.ticket
        while self.flag_grid.count():
            item = self.flag_grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        if not t:
            self.info.setText("No ticket open.")
            self.events.setPlainText("")
            return
        lim = rules.tier_limits(t.tier)
        kind = "  |  TEST TICKET (payment gate off, reports watermarked)" if t.is_test else ""
        self.info.setText(f"{t.id}   |   {t.tier}: up to {lim['small_molecules']} small molecules and {lim['peptides']} peptides   |   "
                          f"TAT {lim['tat']}{kind}")
        flags = t.flags()
        for r, (name, d) in enumerate(rules.flag_defs().items()):
            self.flag_grid.addWidget(label(d["label"], None, False), r, 0)
            chip = label("Yes" if flags[name] else "Not yet", "chipOk" if flags[name] else "chip", False)
            self.flag_grid.addWidget(chip, r, 1)
            allowed = t.is_test or rules.can_set_flag(self.win.operator, name)
            who = ", ".join(d["who"])
            b = button("Mark as done" if not flags[name] else "Undo", True)
            b.setEnabled(allowed)
            b.setToolTip(f"Set by {who}" if not allowed else "")
            b.clicked.connect(lambda _=False, n=name, v=not flags[name]: self._toggle_flag(n, v))
            self.flag_grid.addWidget(b, r, 2)
            self.flag_grid.addWidget(label(f"set by {who}", "muted", False), r, 3)
        self.flag_grid.setColumnStretch(4, 1)
        lines = []
        for e in t.events()[-14:][::-1]:
            data = e.get("data", {})
            extra = f"  {data}" if data else ""
            lines.append(f"{e['utc'][:19].replace('T', ' ')}  {e['actor']:<4} {e['type']}{extra}")
        self.events.setPlainText("\n".join(lines))


# ---------------------------------------------------------------------------------------------------
class ReceptorPage(Page):
    title = "Receptor"
    blurb = "Choose the receptor structure you cleaned in PyMOL. QRKSDock protonates it at pH 7.4 and prepares the search box."

    def __init__(self, win):
        super().__init__(win)
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignLeft)
        form.setVerticalSpacing(10)

        self.pdb_edit = QLineEdit()
        self.pdb_edit.setPlaceholderText("Receptor .pdb file")
        pb = button("Browse…", True)
        pb.clicked.connect(self._pick_pdb)
        r = QHBoxLayout()
        r.addWidget(self.pdb_edit, 1)
        r.addWidget(pb)
        form.addRow("Receptor", r)
        self.inspect_lbl = label("", "muted")
        form.addRow("", self.inspect_lbl)

        self.chain_edit = QLineEdit()
        self.chain_edit.setPlaceholderText("All chains (or e.g. A or A,B)")
        form.addRow("Chains to keep", self.chain_edit)

        self.rb_auto = QRadioButton("Assign protonation at pH")
        self.rb_auto.setChecked(True)
        self.rb_asis = QRadioButton("Already protonated (for example prepared with H++)")
        grp = QButtonGroup(self)
        grp.addButton(self.rb_auto)
        grp.addButton(self.rb_asis)
        self.ph_spin = QDoubleSpinBox()
        self.ph_spin.setRange(0, 14)
        self.ph_spin.setSingleStep(0.1)
        self.ph_spin.setValue(rules.docking_defaults()["ph"])
        pr = QHBoxLayout()
        pr.addWidget(self.rb_auto)
        pr.addWidget(self.ph_spin)
        pr.addWidget(label("with pdb2pqr and PROPKA", "muted", False))
        pr.addStretch(1)
        form.addRow("Protonation", pr)
        form.addRow("", self.rb_asis)

        self.ref_edit = QLineEdit()
        self.ref_edit.setPlaceholderText("Optional: co-crystal ligand as .sdf, .mol or .mol2 (export from PyMOL)")
        rb = button("Browse…", True)
        rb.clicked.connect(self._pick_ref)
        rr = QHBoxLayout()
        rr.addWidget(self.ref_edit, 1)
        rr.addWidget(rb)
        form.addRow("Reference ligand", rr)

        self.box_combo = QComboBox()
        self.box_combo.addItems(["Blind docking: whole receptor", "Around the reference ligand", "Manual box"])
        self.box_combo.currentIndexChanged.connect(self._box_mode_changed)
        form.addRow("Search box", self.box_combo)
        self.manual = [QDoubleSpinBox() for _ in range(6)]
        mg = QHBoxLayout()
        for i, sp in enumerate(self.manual):
            sp.setRange(-9999, 9999)
            sp.setDecimals(2)
            if i >= 3:
                sp.setRange(1, 300)
                sp.setValue(25)
            mg.addWidget(label(("cx", "cy", "cz", "sx", "sy", "sz")[i], "muted", False))
            mg.addWidget(sp)
        self.manual_w = QWidget()
        self.manual_w.setLayout(mg)
        mg.setContentsMargins(0, 0, 0, 0)
        form.addRow("", self.manual_w)
        self.allow_bad = QCheckBox("Allow removing residues that cannot be parameterized")
        form.addRow("", self.allow_bad)
        self.body.addLayout(form)

        self.go = button("Prepare receptor and box")
        self.go.clicked.connect(self._prepare)
        self.body.addWidget(self.go, 0, Qt.AlignLeft)
        self.result = label("", "summary")
        self.result.hide()
        self.body.addWidget(self.result)
        self.notes = label("", "warn")
        self.notes.hide()
        self.body.addWidget(self.notes)
        self.body.addStretch(1)
        self._box_mode_changed()

    def _box_mode_changed(self):
        self.manual_w.setVisible(self.box_combo.currentIndex() == 2)

    def _pick_pdb(self):
        f, _ = QFileDialog.getOpenFileName(self, "Receptor structure", "", "PDB files (*.pdb *.ent);;All files (*)")
        if f:
            self.pdb_edit.setText(f)
            try:
                s = receptor.inspect_pdb(Path(f))
                self.inspect_lbl.setText(s.text().replace("\n", "   |   ") + ("\n" + " ".join(s.warnings) if s.warnings else ""))
            except Exception as exc:                                                    # noqa: BLE001
                self.inspect_lbl.setText(f"Could not read this file: {exc}")

    def _pick_ref(self):
        f, _ = QFileDialog.getOpenFileName(self, "Reference ligand", "", "Ligand files (*.sdf *.mol *.mol2);;All files (*)")
        if f:
            self.ref_edit.setText(f)

    def _prepare(self):
        w = self.win
        if not w.require_ticket():
            return
        pdb = self.pdb_edit.text().strip()
        if not pdb or not Path(pdb).is_file():
            QMessageBox.warning(self, "Receptor", "Choose a receptor .pdb file first.")
            return
        ref = self.ref_edit.text().strip() or None
        mode = ("blind", "reference", "manual")[self.box_combo.currentIndex()]
        chains = [c.strip() for c in self.chain_edit.text().split(",") if c.strip()] or None
        manual = None
        if mode == "manual":
            v = [sp.value() for sp in self.manual]
            manual = (tuple(v[:3]), tuple(v[3:]))
        proj = w.project
        kwargs = dict(method="pdb2pqr" if self.rb_auto.isChecked() else "as_is", chains=chains, ph=self.ph_spin.value(),
                      box_mode=mode, reference_path=Path(ref) if ref else None, manual_box=manual,
                      allow_bad_res=self.allow_bad.isChecked())

        def job(log, progress, cancel):
            progress(0.05, "Preparing receptor")
            return proj.prepare_receptor(Path(pdb), log=log, **kwargs)

        def done(res):
            self.result.setText(f"{res['box'].summary()}\nRecommended exhaustiveness for this box: {res['recommended_exhaustiveness']}")
            self.result.show()
            warns = res["warnings"]
            self.notes.setText("\n".join(warns))
            self.notes.setVisible(bool(warns))
            w.pages[3]._touched = False
            w.refresh()

        w.run_job(job, done, "Preparing receptor…")

    def refresh(self):
        w = self.win
        if w.project and w.project.receptor_ready:
            box = w.project.box
            if not self.result.isVisible():
                self.result.setText(box.summary() + f"\nRecommended exhaustiveness for this box: {boxmod.recommended_exhaustiveness(box)}")
                self.result.show()
                warns = w.project.s["receptor"].get("warnings", [])
                self.notes.setText("\n".join(warns))
                self.notes.setVisible(bool(warns))
        else:
            self.result.hide()
            self.notes.hide()


# ---------------------------------------------------------------------------------------------------
class LigandsPage(Page):
    title = "Ligands"
    blurb = "One ligand per line. Small molecules as 'SMILES name', peptides as 'SEQUENCE name' (2-6 residues, one-letter codes)."

    def __init__(self, win):
        super().__init__(win)
        self.tabs = QTabWidget()
        self.small = QPlainTextEdit()
        self.small.setPlaceholderText("C1=CC=C(C(=C1)C(=O)C[C@@H](C(=O)O)N)N  L-kynurenine\n# lines starting with # are ignored")
        self.pept = QPlainTextEdit()
        self.pept.setPlaceholderText("GW  dipeptide_GW\nLLPK  tetrapeptide_1")
        for w_ in (self.small, self.pept):
            mono(w_)
            w_.textChanged.connect(self._counts)
        self.tabs.addTab(self.small, "Small molecules")
        self.tabs.addTab(self.pept, "Peptides")
        self.tabs.setMaximumHeight(210)
        self.body.addWidget(self.tabs)

        row = QHBoxLayout()
        load = button("Load file…", True)
        load.clicked.connect(self._load)
        self.policy = QComboBox()
        self.policy.setMinimumContentsLength(26)
        self.policy.addItems(["Undefined stereo: warn", "Undefined stereo: block", "Undefined stereo: dock all isomers"])
        self.count_lbl = label("", "muted", False)
        self.check_btn = button("Check ligands", True)
        self.prep_btn = button("Prepare ligands")
        self.check_btn.clicked.connect(self._check)
        self.prep_btn.clicked.connect(self._prepare)
        for w_ in (load, self.policy):
            row.addWidget(w_)
        row.addStretch(1)
        row.addWidget(self.check_btn)
        row.addWidget(self.prep_btn)
        self.body.addLayout(row)
        self.body.addWidget(self.count_lbl)

        self.table = QTableWidget()
        self.body.addWidget(self.table, 1)
        self._counts()

    def _policy(self) -> str:
        return ("warn", "block", "enumerate")[self.policy.currentIndex()]

    def _inputs(self):
        return (ligands.parse_smiles_text(self.small.toPlainText()), ligands.parse_peptide_text(self.pept.toPlainText()))

    def _counts(self):
        s, p = self._inputs()
        t = self.win.ticket if hasattr(self.win, "ticket") else None
        if t:
            lim = rules.tier_limits(t.tier)
            self.count_lbl.setText(f"Small molecules {len(s)}/{lim['small_molecules']}   Peptides {len(p)}/{lim['peptides']}")
        else:
            self.count_lbl.setText(f"Small molecules {len(s)}   Peptides {len(p)}")

    def _load(self):
        f, _ = QFileDialog.getOpenFileName(self, "Ligand file", "", "Ligand files (*.smi *.txt *.csv *.sdf *.mol);;All files (*)")
        if f:
            try:
                text, _ins = ligands.read_ligand_file(Path(f))
            except Exception as exc:                                                    # noqa: BLE001
                QMessageBox.warning(self, "Load file", str(exc))
                return
            self.small.setPlainText(text)
            self.tabs.setCurrentIndex(0)

    def _show_checks(self, checks):
        rows, colors_ = [], []
        for c in checks:
            note = " ".join(c.errors + c.warnings)
            rows.append([c.name, c.kind.replace("_", " "), c.heavy_atoms, f"{c.mass:.1f}", c.rot_bonds, c.stereo_text, note])
            colors_.append("#FBE3E0" if c.errors else ("#FFF6E0" if c.warnings else None))
        fill_table(self.table, ["Name", "Type", "Heavy atoms", "Mass (Da)", "Rotatable bonds", "Stereochemistry", "Notes"], rows, colors_, 6)

    def _check(self):
        s, p = self._inputs()
        if not (s or p):
            QMessageBox.information(self, "Ligands", "Add at least one ligand first.")
            return
        self._show_checks(ligands.check_ligands(s + p, self._policy()))

    def _prepare(self):
        w = self.win
        if not w.require_ticket():
            return
        proj, small, pept, policy = w.project, self.small.toPlainText(), self.pept.toPlainText(), self._policy()
        ph = rules.docking_defaults()["ph"]
        seed = rules.docking_defaults()["ligand_prep_seed"]
        self._check()

        def job(log, progress, cancel):
            return proj.prepare_ligands(small, pept, stereo_policy=policy, ph=ph, seed=seed, log=log, progress=progress)

        def done(checks):
            self._show_checks(checks)
            w.refresh()

        w.run_job(job, done, "Preparing ligands…")

    def refresh(self):
        self._counts()
        w = self.win
        if w.project and w.project.s.get("ligand_inputs") and not self.small.toPlainText() and not self.pept.toPlainText():
            ins = w.project.s["ligand_inputs"]
            self.small.setPlainText("\n".join(f"{i['smiles']} {i['name']}" for i in ins if i["kind"] == "small_molecule"))
            self.pept.setPlainText("\n".join(f"{i['sequence']} {i['name']}" for i in ins if i["kind"] == "peptide"))


# ---------------------------------------------------------------------------------------------------
class DockingPage(Page):
    title = "Docking"
    blurb = "Validate the setup by redocking the reference ligand, then dock your ligands with AutoDock Vina."

    def __init__(self, win):
        super().__init__(win)
        grid = QGridLayout()
        grid.setHorizontalSpacing(18)
        self.exh = QSpinBox()
        self.exh.setRange(1, 256)
        self.exh.setValue(16)
        self.poses = QSpinBox()
        self.poses.setRange(1, 20)
        self.poses.setValue(rules.docking_defaults()["num_modes"])
        self.erange = QDoubleSpinBox()
        self.erange.setRange(0.5, 20)
        self.erange.setValue(rules.docking_defaults()["energy_range"])
        self.cpu = QSpinBox()
        self.cpu.setRange(1, os.cpu_count() or 1)
        self.cpu.setValue(vina_runner.default_cpus())
        self._touched = False
        self.exh.valueChanged.connect(lambda _v: setattr(self, "_touched", True))
        for i, (name, w_) in enumerate((("Exhaustiveness", self.exh), ("Poses per ligand", self.poses), ("Energy range (kcal/mol)", self.erange),
                                        ("CPU threads", self.cpu))):
            grid.addWidget(label(name, "muted", False), 0, i)
            grid.addWidget(w_, 1, i)
        self.body.addLayout(grid)
        self.rec_lbl = label("", "muted")
        self.body.addWidget(self.rec_lbl)

        row = QHBoxLayout()
        self.val_btn = button("Run validation (redock reference)", True)
        self.run_btn = button("Run docking")
        self.cancel_btn = button("Cancel", True)
        self.cancel_btn.setEnabled(False)
        self.val_btn.clicked.connect(self._validate)
        self.run_btn.clicked.connect(self._dock)
        self.cancel_btn.clicked.connect(self.win.cancel_job)
        for b in (self.val_btn, self.run_btn, self.cancel_btn):
            row.addWidget(b)
        row.addStretch(1)
        self.body.addLayout(row)
        self.val_lbl = label("", "summary")
        self.val_lbl.hide()
        self.body.addWidget(self.val_lbl)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        mono(self.log)
        self.body.addWidget(self.log, 1)

    def params(self) -> DockParams:
        return DockParams(exhaustiveness=self.exh.value(), num_modes=self.poses.value(), energy_range=self.erange.value(),
                          cpu=self.cpu.value(), ph=rules.docking_defaults()["ph"])

    def append(self, text: str):
        self.log.appendPlainText(text)

    def _validate(self):
        w = self.win
        if not w.require_ticket():
            return
        proj, params = w.project, self.params()

        def job(log, progress, cancel):
            return proj.run_validation(params, vina_path=w.vina_path, log=log, progress=progress, cancel=cancel)

        def done(val):
            self._show_validation(val)
            w.refresh()

        w.run_job(job, done, "Redocking reference ligand…", log_to=self.append, cancellable=True)

    def _show_validation(self, val):
        self.val_lbl.setText(val.text())
        self.val_lbl.setObjectName("summaryOk" if val.passed else "summaryBad")
        self.val_lbl.style().unpolish(self.val_lbl)
        self.val_lbl.style().polish(self.val_lbl)
        self.val_lbl.show()

    def _dock(self):
        w = self.win
        if not w.require_ticket():
            return
        proj, params = w.project, self.params()
        if proj.reference_ready and not proj.validation:
            if QMessageBox.question(self, "No validation yet", "The reference ligand has not been redocked yet. "
                                    "Run docking without validation?") != QMessageBox.Yes:
                return

        def job(log, progress, cancel):
            return proj.run_docking(params, vina_path=w.vina_path, log=log, progress=progress, cancel=cancel)

        def done(_res):
            w.refresh()
            w.goto("Results")

        w.run_job(job, done, "Docking…", log_to=self.append, cancellable=True)

    def set_busy(self, busy: bool):
        p = self.win.project
        self.val_btn.setEnabled(not busy and bool(p and p.receptor_ready and p.reference_ready))
        self.run_btn.setEnabled(not busy and bool(p and p.receptor_ready and p.ligands_ready))
        self.cancel_btn.setEnabled(busy)

    def refresh(self):
        w = self.win
        p = w.project
        self.set_busy(w.busy)
        if p and p.box:
            rec = boxmod.recommended_exhaustiveness(p.box)
            self.rec_lbl.setText(f"Recommended exhaustiveness for the current box: {rec}. Vina's default of 8 is meant for small boxes.")
            if not self._touched and p.receptor_ready and self.exh.value() != rec:
                self.exh.blockSignals(True)                      # programmatic change: not "touched"
                self.exh.setValue(rec)
                self.exh.blockSignals(False)
        v = p.validation if p else None
        if v:
            self._show_validation(v)
        else:
            self.val_lbl.hide()


# ---------------------------------------------------------------------------------------------------
class ResultsPage(Page):
    title = "Results"
    blurb = "Ranked by the predicted binding affinity of each ligand's best pose. Double-click a ligand name to rename it; exports and reports use the new name."
    HEAD = ["Rank", "Ligand", "Type", "Best state", "Affinity (kcal/mol)", "Est. pKd", "Contact residues", "Polar contacts"]

    def __init__(self, win):
        super().__init__(win)
        self._filling = False
        self.best = label("", "callout")
        self.best.hide()
        self.body.addWidget(self.best)
        self.table = QTableWidget()
        self.table.itemChanged.connect(self._on_edit)
        self.table.itemSelectionChanged.connect(self._show_poses)
        self.table.setMinimumHeight(150)
        self.body.addWidget(self.table, 2)
        self.pose_title = label("", "h2", False)
        self.body.addWidget(self.pose_title)
        self.pose_table = QTableWidget()
        self.pose_table.verticalHeader().setDefaultSectionSize(26)
        self.pose_table.setMinimumHeight(10 * 26 + 38)           # all 10 poses visible without scrolling
        self.body.addWidget(self.pose_table, 2)
        self.note = label("Estimated pKd = -dG / (2.303 R T) at 298 K from the Vina score. It is a rough conversion for ranking, not a measured affinity.", "muted")
        self.body.addWidget(self.note)
        self.state_lbl = label("", "muted")
        self.body.addWidget(self.state_lbl)
        row = QHBoxLayout()
        self.csv_btn = button("Export CSV…", True)
        self.log_btn = button("Save Vina log…", True)
        self.folder_btn = button("Open results folder", True)
        self.report_btn = button("Generate PDF report")
        self.open_report_btn = button("Open report", True)
        self.csv_btn.clicked.connect(self._export)
        self.log_btn.clicked.connect(self._save_log)
        self.folder_btn.clicked.connect(lambda: self.win.ticket and open_path(self.win.ticket.sub("results")))
        self.report_btn.clicked.connect(self._report)
        self.open_report_btn.clicked.connect(self._open_report)
        for b in (self.csv_btn, self.log_btn, self.folder_btn):
            row.addWidget(b)
        row.addStretch(1)
        row.addWidget(self.open_report_btn)
        row.addWidget(self.report_btn)
        self.body.addLayout(row)
        self._last_report: Path | None = None
        self._rows: list = []

    # ---- editing -------------------------------------------------------------------------------
    def _on_edit(self, item):
        if self._filling or item.column() != 1:
            return
        p = self.win.project
        try:
            p.rename_ligand(item.data(Qt.UserRole), item.text())
        except Exception as exc:                                     # noqa: BLE001
            QMessageBox.warning(self, "Rename ligand", str(exc))
        self.win.refresh()

    # ---- exports ---------------------------------------------------------------------------------
    def _export(self):
        p = self.win.project
        if not p or not p.results:
            return
        p.export_results()
        dest, _ = QFileDialog.getSaveFileName(self, "Export results", f"{self.win.ticket.id}_results.csv", "CSV (*.csv)")
        if dest:
            res = self.win.ticket.sub("results")
            shutil.copy2(res / "results.csv", dest)
            shutil.copy2(res / "poses.csv", Path(dest).with_name(Path(dest).stem + "_poses.csv"))

    def _save_log(self):
        log = self.win.ticket.sub("results") / "vina_output.log" if self.win.ticket else None
        if not log or not log.exists():
            QMessageBox.information(self, "Vina log", "Run docking first.")
            return
        dest, _ = QFileDialog.getSaveFileName(self, "Save Vina log", "vina_output.log", "Log files (*.log)")
        if dest:
            shutil.copy2(log, dest)

    def _report(self):
        w = self.win
        if not w.require_ticket():
            return
        try:
            self._last_report = generate_report(w.project, w.operator)
        except (PermissionDenied, ValueError, OSError) as exc:
            QMessageBox.warning(self, "Report", str(exc))
            return
        w.refresh()
        open_path(self._last_report)

    def _open_report(self):
        if self._last_report and self._last_report.exists():
            open_path(self._last_report)
        elif self.win.ticket:
            open_path(self.win.ticket.sub("reports"))

    # ---- display -------------------------------------------------------------------------------------
    def _show_poses(self):
        p = self.win.project
        sel = self.table.selectionModel().selectedRows() if self.table.selectionModel() else []
        if not p or not self._rows or not sel:
            self.pose_title.setText("")
            fill_table(self.pose_table, ["Pose", "Affinity (kcal/mol)", "Est. pKd", "RMSD l.b. (Å)", "RMSD u.b. (Å)"], [])
            return
        r = self._rows[sel[0].row()]
        from qrksdock.core import thermo
        rows = [[k + 1, f"{a:.2f}", f"{thermo.estimate_pkd(a):.2f}",
                 f"{r.rmsd_lb[k]:.2f}" if k < len(r.rmsd_lb) else "", f"{r.rmsd_ub[k]:.2f}" if k < len(r.rmsd_ub) else ""]
                for k, a in enumerate(r.affinities)]
        self.pose_title.setText(f"Top {len(rows)} poses of {p.display_state(r)} (ranked by affinity)")
        fill_table(self.pose_table, ["Pose", "Affinity (kcal/mol)", "Est. pKd", "RMSD l.b. (Å)", "RMSD u.b. (Å)"], rows)

    def refresh(self):
        w = self.win
        p = w.project
        res = p.best_per_ligand() if p else []
        has = bool(res)
        for b in (self.csv_btn, self.log_btn, self.folder_btn, self.report_btn, self.open_report_btn):
            b.setEnabled(has)
        self._rows = res
        self._filling = True
        try:
            if not has:
                self.best.hide()
                fill_table(self.table, self.HEAD, [])
                self.state_lbl.setText("Run docking to see results here.")
            else:
                top = res[0]
                self.best.setText(f"Best predicted binder: {p.display_ligand(top.ligand)}   {top.best_affinity:.2f} kcal/mol   (est. pKd {top.pkd:.1f})")
                self.best.show()
                multi = {r.ligand: sum(1 for x in p.results if x.ligand == r.ligand) > 1 for r in res}
                rows = [[i, p.display_ligand(r.ligand), r.kind.replace("_", " "),
                         p.display_state(r) if multi[r.ligand] else "-", f"{r.best_affinity:.2f}", f"{r.pkd:.2f}",
                         len(r.contact_residues), len(r.polar_contacts)] for i, r in enumerate(res, 1)]
                fill_table(self.table, self.HEAD, rows, ["#FDF1C9"] + [None] * (len(rows) - 1), 1,
                           editable_cols={1}, row_ids=[r.ligand for r in res])
                rs = w.ticket.report_state()
                bits = ["Integrity Seal will be applied." if rs["seal"] else "Integrity Seal withheld until QA passes and the report is signed.",
                        "Report is watermarked." if rs["watermark"] else "Report is unwatermarked (balance cleared)."]
                self.state_lbl.setText("  ".join(bits) + f"   Run ID {p.s.get('run_id', '')}")
        finally:
            self._filling = False
        if has:
            self.table.selectRow(0)
        self._show_poses()
