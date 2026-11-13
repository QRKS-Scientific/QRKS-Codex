"""The five workflow pages. Each page reads and writes through `win.project`; no science here."""
from __future__ import annotations

import base64
import binascii
import os
import shutil
from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QColor, QDesktopServices, QFontDatabase, QImage
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QButtonGroup, QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog, QFormLayout,
                               QFrame, QGridLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMessageBox,
                               QPlainTextEdit, QProgressBar, QPushButton, QRadioButton, QSizePolicy, QSpinBox,
                               QTableWidget, QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget)

from qrksdock import brand
from qrksdock.core import box as boxmod
from qrksdock.core import ligands, receptor, rules, vina_runner
from qrksdock.core.pipeline import DockParams, Project
from qrksdock.core.report import generate_report
from qrksdock.core.runs import Run, RunError, list_runs, next_qdock_code, normalize_client_code
from qrksdock.net.errors import NetError, Offline
from qrksdock.gui.viewer import MolViewer

P = brand.ACTIVE


def open_path(path: Path) -> None:
    QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))


def label(text: str, role: str | None = None, wrap: bool = True) -> QLabel:
    lb = QLabel(text)
    if role:
        lb.setObjectName(role)
    lb.setWordWrap(wrap)
    lb.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    return lb


def button(text: str, secondary: bool = False) -> QPushButton:
    b = QPushButton(text)
    if secondary:
        b.setObjectName("secondary")
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    return b


def field(title: str, widget: QWidget, guide: str = "") -> QWidget:
    """A titled input with a short guide underneath. The guide wraps, so nothing is ever cut off."""
    box = QWidget()
    v = QVBoxLayout(box)
    v.setContentsMargins(0, 0, 0, 0)
    v.setSpacing(6)
    t = QLabel(title)
    t.setObjectName("fieldTitle")
    v.addWidget(t)
    v.addWidget(widget)
    if guide:
        v.addWidget(label(guide, "guide"))
    return box


def panel(title: str) -> tuple[QFrame, QVBoxLayout]:
    f = QFrame()
    f.setStyleSheet(f"QFrame#panel {{ background: {P.surface}; border: 1px solid {P.border}; border-radius: 10px; }}")
    f.setObjectName("panel")
    v = QVBoxLayout(f)
    v.setContentsMargins(20, 18, 20, 18)
    v.setSpacing(10)
    v.addWidget(label(title, "h2"))
    return f, v


def mono(widget) -> None:
    widget.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))


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
                    it.setData(Qt.ItemDataRole.UserRole, row_ids[r])
            else:
                it.setFlags(it.flags() & ~Qt.ItemFlag.ItemIsEditable)
            if row_colors and row_colors[r]:
                it.setBackground(QColor(row_colors[r]))
            table.setItem(r, c, it)
    table.verticalHeader().setVisible(False)
    table.setEditTriggers(QAbstractItemView.EditTrigger.DoubleClicked if editable_cols else QAbstractItemView.EditTrigger.NoEditTriggers)
    table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    table.setAlternatingRowColors(not row_colors)
    hh = table.horizontalHeader()
    hh.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
    hh.setStretchLastSection(True)                       # the header band always spans the full width
    hh.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
    if stretch_col is not None:
        hh.setSectionResizeMode(stretch_col, QHeaderView.ResizeMode.Stretch)
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
class ProjectPage(Page):
    title = "Project"
    blurb = ("Every docking run has a client code (QC-001) and a QDOCK code (QDOCK-260824-001). "
             "A run is a plain folder, so it syncs with Google Drive like any other.")
    RUN_HEAD = ["Client", "QDOCK code", "Created", "By", "Package", "Stage", "Ligands", "Best (kcal/mol)", "Reports"]

    def __init__(self, win):
        super().__init__(win)
        row = QHBoxLayout()
        self.root_edit = QLineEdit(win.settings.value("runs_root", str(Path.home() / "Documents" / "QRKS Runs")))
        self.root_edit.editingFinished.connect(self._root_changed)
        b = button("Browse…", True)
        b.clicked.connect(self._browse_root)
        row.addWidget(label("Runs folder", "h2", False))
        row.addWidget(self.root_edit, 1)
        row.addWidget(b)
        self.body.addLayout(row)

        row2 = QHBoxLayout()
        self.client_edit = QLineEdit()
        self.client_edit.setPlaceholderText("Client code, e.g. QC-001")
        self.client_edit.setMinimumWidth(220)
        self.pkg_combo = QComboBox()
        self.pkg_combo.addItem("No package limit", "")
        for t in rules.tiers():
            lim = rules.tier_limits(t)
            self.pkg_combo.addItem(f"{t}: {lim['small_molecules']} small molecules, {lim['peptides']} peptides", t)
        self.pkg_combo.setMinimumContentsLength(34)
        self.new_btn = button("New Run")
        self.open_btn = button("Open run folder…", True)
        self.new_btn.clicked.connect(self._new)
        self.open_btn.clicked.connect(self._open)
        for w_ in (label("New run for", "muted", False), self.client_edit, self.pkg_combo):
            row2.addWidget(w_)
        row2.addStretch(1)
        row2.addWidget(self.new_btn)
        row2.addWidget(self.open_btn)
        self.body.addLayout(row2)
        self.next_lbl = label("", "muted")
        self.body.addWidget(self.next_lbl)

        self.info = label("No run open.", "summary")
        self.body.addWidget(self.info)

        self.body.addWidget(label("All runs in this folder (double-click to open)", "h2", False))
        self.runs = QTableWidget()
        self.runs.setMinimumHeight(170)
        self.runs.cellDoubleClicked.connect(self._open_row)
        self.body.addWidget(self.runs, 2)
        self.body.addWidget(label("Activity in the open run", "h2", False))
        self.activity = QPlainTextEdit()
        self.activity.setReadOnly(True)
        mono(self.activity)
        self.body.addWidget(self.activity, 1)
        self._paths: list[Path] = []

    # ---- folder ---------------------------------------------------------------------------
    def root(self) -> Path:
        return Path(self.root_edit.text().strip() or ".").expanduser()

    def _root_changed(self):
        self.win.settings.setValue("runs_root", str(self.root()))
        self.refresh()

    def _browse_root(self):
        d = QFileDialog.getExistingDirectory(self, "Choose the runs folder (for example inside Google Drive)", str(self.root()))
        if d:
            self.root_edit.setText(d)
            self._root_changed()

    # ---- create / open ------------------------------------------------------------------------
    def _new(self):
        try:
            client = normalize_client_code(self.client_edit.text())
            package = self.pkg_combo.currentData() or None
            code = None
            if self.win.net:                                         # the server issues codes, so two laptops can never collide
                QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
                try:
                    code = self.win.net.create_run(client, package or "")
                finally:
                    QApplication.restoreOverrideCursor()
            run = Run.create(self.root(), client, self.win.operator, package, qdock_code=code)
        except Offline:
            QMessageBox.warning(self, "New run", "Creating a run needs a connection to the QRKS server, so QDOCK codes stay unique across laptops. "
                                "Connect to the internet and try again, or open an existing run to keep working offline.")
            return
        except (RunError, NetError, OSError) as exc:
            QMessageBox.warning(self, "New run", str(exc))
            return
        self.win.settings.setValue("runs_root", str(self.root()))
        self.win.set_run(run)

    def _open(self):
        d = QFileDialog.getExistingDirectory(self, "Open a run folder (QDOCK-…)", str(self.root()))
        if d:
            self._open_path(Path(d))

    def _open_row(self, row: int, _col: int):
        if 0 <= row < len(self._paths):
            self._open_path(self._paths[row])

    def _open_path(self, path: Path):
        try:
            self.win.set_run(Run.open(path, self.win.operator))
        except (RunError, OSError) as exc:
            QMessageBox.warning(self, "Open run", str(exc))

    # ---- display ---------------------------------------------------------------------------------
    def refresh(self):
        root = self.root()
        if self.win.net:
            self.next_lbl.setText("The QRKS server issues the next QDOCK code when you create the run.")
        else:
            self.next_lbl.setText(f"The next QDOCK code in this folder will be {next_qdock_code(root)}.")
        run = self.win.run
        if run:
            pkg = f"   |   Package {run.package}" if run.package else "   |   No package limit"
            self.info.setText(f"{run.client}   |   {run.code}{pkg}   |   created {run.meta.get('created_utc', '')[:10]} by {run.meta.get('created_by', '')}\n{run.path}")
        else:
            self.info.setText("No run open. Create one above, or double-click a run in the table.")
        runs = list_runs(root)
        self._paths = [r["path"] for r in runs]
        rows = [[r["client"], r["code"], r["created"], r["by"], r["package"] or "-", r["stage"], r["ligands"] or "-",
                 f"{r['best']:.2f}" if r["best"] is not None else "-", r["reports"] or "-"] for r in runs]
        colors = ["#D9E8FB" if run and r["path"].resolve() == run.path.resolve() else None for r in runs]
        fill_table(self.runs, self.RUN_HEAD, rows, colors if any(colors) else None)
        lines = []
        for e in (run.activity(14)[::-1] if run else []):
            data = e.get("data", {})
            lines.append(f"{e['utc'][:19].replace('T', ' ')}  {e['actor']:<4} {e['type']}" + (f"  {data}" if data else ""))
        self.activity.setPlainText("\n".join(lines))


# ---------------------------------------------------------------------------------------------------
# ---------------------------------------------------------------------------------------------------
class ReceptorPage(Page):
    title = "Receptor"
    blurb = "Choose the receptor you cleaned in PyMOL. QRKSDock protonates it at pH 7.4 and prepares the search box."

    def __init__(self, win):
        super().__init__(win)
        cols = QHBoxLayout()
        cols.setSpacing(24)
        left = QVBoxLayout()
        left.setSpacing(16)

        self.pdb_edit = QLineEdit()
        self.pdb_edit.setPlaceholderText("Choose a receptor .pdb file")
        pb = button("Browse…", True)
        pb.clicked.connect(self._pick_pdb)
        r = QHBoxLayout()
        r.addWidget(self.pdb_edit, 1)
        r.addWidget(pb)
        rw = QWidget()
        rw.setLayout(r)
        r.setContentsMargins(0, 0, 0, 0)
        left.addWidget(field("Receptor structure", rw, "A .pdb file. Waters, ligands, ions and cofactors are removed during preparation."))
        self.inspect_lbl = label("", "muted")
        self.inspect_lbl.hide()
        left.addWidget(self.inspect_lbl)

        self.chain_edit = QLineEdit()
        self.chain_edit.setPlaceholderText("All chains")
        left.addWidget(field("Chains to keep", self.chain_edit, "Leave empty to keep every chain, or type one chain (A) or several (A,B)."))

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
        pr.addStretch(1)
        pw = QWidget()
        pw.setLayout(pr)
        pr.setContentsMargins(0, 0, 0, 0)
        pv = QVBoxLayout()
        pv.setSpacing(8)
        pv.addWidget(pw)
        pv.addWidget(self.rb_asis)
        pbox = QWidget()
        pbox.setLayout(pv)
        pv.setContentsMargins(0, 0, 0, 0)
        left.addWidget(field("Protonation", pbox, "pdb2pqr with PROPKA assigns charges at this pH. Choose the second option only if the file already has hydrogens you trust."))

        self.ref_edit = QLineEdit()
        self.ref_edit.setPlaceholderText("Optional: the co-crystal ligand (.sdf, .mol or .mol2)")
        rb = button("Browse…", True)
        rb.clicked.connect(self._pick_ref)
        rr = QHBoxLayout()
        rr.addWidget(self.ref_edit, 1)
        rr.addWidget(rb)
        rrw = QWidget()
        rrw.setLayout(rr)
        rr.setContentsMargins(0, 0, 0, 0)
        left.addWidget(field("Reference ligand", rrw, "Export it from PyMOL as .sdf (a PDB loses the bond orders). It lets you validate the setup by redocking and centre the box on it."))

        self.box_combo = QComboBox()
        self.box_combo.addItems(["Blind docking: whole receptor", "Around the reference ligand", "Manual box"])
        self.box_combo.currentIndexChanged.connect(self._box_mode_changed)
        left.addWidget(field("Search box", self.box_combo, "Blind docking searches the whole protein and is slower. A box around a known ligand is faster and more accurate."))

        self.manual = [QDoubleSpinBox() for _ in range(6)]
        mg = QGridLayout()
        mg.setHorizontalSpacing(10)
        mg.setVerticalSpacing(8)
        mg.addWidget(label("Box centre (Å)", "fieldTitle", False), 0, 0)
        mg.addWidget(label("Box size (Å)", "fieldTitle", False), 2, 0)
        for i, sp in enumerate(self.manual):
            sp.setRange(-9999, 9999)
            sp.setDecimals(2)
            sp.setPrefix(("X  ", "Y  ", "Z  ")[i % 3])
            sp.setMinimumWidth(130)
            if i >= 3:
                sp.setRange(1, 300)
                sp.setValue(25)
            # --- LIVE SPINBOX CONNECTION ---
            sp.valueChanged.connect(self._draw_manual_box)
            mg.addWidget(sp, 1 if i < 3 else 3, i % 3)
        self.manual_w = QWidget()
        self.manual_w.setLayout(mg)
        mg.setContentsMargins(0, 0, 0, 0)
        left.addWidget(self.manual_w)

        self.allow_bad = QCheckBox("Allow removing residues that cannot be parameterized")
        left.addWidget(self.allow_bad)
        self.go = button("Prepare receptor and box")
        self.go.clicked.connect(self._prepare)
        left.addWidget(self.go, 0, Qt.AlignmentFlag.AlignLeft)
        left.addStretch(1)

        # --- RIGHT COLUMN: VIEWER + SUMMARY ---
        right_col = QVBoxLayout()
        right_col.setSpacing(16)

        self.viewer = MolViewer()
        right_col.addWidget(self.viewer, 6)

        right_panel, rv = panel("Preparation summary")
        self.result = label("Nothing prepared yet. Choose a receptor and click Prepare receptor and box.", "muted")
        self.result.setTextFormat(Qt.TextFormat.RichText)
        rv.addWidget(self.result)
        self.notes = label("", "warn")
        self.notes.hide()
        rv.addWidget(self.notes)
        rv.addStretch(1)
        right_col.addWidget(right_panel, 4)

        cols.addLayout(left, 6)
        cols.addLayout(right_col, 4)
        self.body.addLayout(cols, 1)
        self._box_mode_changed()

    def _box_mode_changed(self):
        is_manual = self.box_combo.currentIndex() == 2
        self.manual_w.setVisible(is_manual)
        if is_manual:
            self._draw_manual_box()
        else:
            if hasattr(self, "viewer"):
                self.viewer.clear_shapes()

    def _draw_manual_box(self, *_):
        """Redraws the magenta wireframe box in the 3D viewer when spinboxes change."""
        if hasattr(self, "viewer") and self.box_combo.currentIndex() == 2:
            v = [sp.value() for sp in self.manual]
            self.viewer.add_box(tuple(v[:3]), tuple(v[3:]))

    def _pick_pdb(self):
        f, _ = QFileDialog.getOpenFileName(self, "Receptor structure", "", "PDB files (*.pdb *.ent);;All files (*)")
        if f:
            self.pdb_edit.setText(f)
            try:
                pdb_text = Path(f).read_text(encoding="utf-8")
                self.viewer.load_receptor(pdb_text, "pdb")
                s = receptor.inspect_pdb(Path(f))
                self.inspect_lbl.setText(s.text().replace("\n", "   |   ") + ("\n" + " ".join(s.warnings) if s.warnings else ""))
                self.inspect_lbl.show()
            except Exception as exc:
                self.inspect_lbl.setText(f"Could not read this file: {exc}")
                self.inspect_lbl.show()

    def _pick_ref(self):
        f, _ = QFileDialog.getOpenFileName(self, "Reference ligand", "", "Ligand files (*.sdf *.mol *.mol2);;All files (*)")
        if f:
            self.ref_edit.setText(f)
            try:
                # --- INSTANT REFERENCE LIGAND PREVIEW ---
                raw_ref = Path(f).read_text(encoding="utf-8")
                fmt = Path(f).suffix.lstrip(".").lower()
                if fmt in ["sdf", "mol", "mol2"]:
                    self.viewer.add_reference(raw_ref, fmt)
            except Exception:
                pass

    def _prepare(self):
        w = self.win
        if not w.require_run():
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

        def done(_res):
            w.pages[3]._touched = False
            w.refresh()

        w.run_job(job, done, "Preparing receptor…")

    def _style(self, name: str) -> None:
        self.result.setObjectName(name)
        self.result.style().unpolish(self.result)
        self.result.style().polish(self.result)

    @staticmethod
    def _rows(rows: list[tuple[str, str]]) -> str:
        from html import escape
        return "".join(f"<p style='margin:0 0 9px 0'><span style='color:{P.muted}'>{escape(k)}</span><br>"
                       f"<b>{escape(v)}</b></p>" for k, v in rows)

    def refresh(self):
        p = self.win.project
        if p and p.receptor_ready:
            rec = p.s["receptor"]
            removed = ", ".join(f"{k} x{v}" for k, v in rec["removed"].items()) or "none"
            states = ", ".join(f"{k} x{v}" for k, v in rec["residue_states"].items()) or "none assigned"
            prot = f"pdb2pqr with PROPKA at pH {rec['ph']}" if rec["method"] == "pdb2pqr" else "supplied by you (already protonated)"

            self._style("")
            self.result.setText(self._rows([
                ("Search box", p.box.summary()),
                ("Recommended exhaustiveness for this box", str(boxmod.recommended_exhaustiveness(p.box))),
                ("Chains kept", ", ".join(rec["chains_kept"])),
                ("Removed from the receptor", removed),
                ("Protonation", prot),
                ("Histidine and other titratable states", states),
                ("Reference ligand", "ready for validation" if p.reference_ready else "none")
            ]))

            warns = rec.get("warnings", [])
            self.notes.setText("\n".join(warns))
            self.notes.setVisible(bool(warns))

            # LOAD RECEPTOR, BOX, AND REFERENCE INTO VIEWER ON REOPEN:
            pdb_path = self.win.run.path / rec["clean_pdb"]
            if pdb_path.exists():
                try:
                    self.viewer.load_receptor(pdb_path.read_text(encoding="utf-8"), "pdb")
                    if p.box and p.box.mode == "manual":
                        self.viewer.add_box(p.box.center, p.box.size)
                    if p.reference_ready:
                        sdf_path = self.win.run.path / p.s["reference"]["sdf"]
                        if sdf_path.exists():
                            self.viewer.add_reference(sdf_path.read_text(encoding="utf-8"), "sdf")
                except Exception:
                    pass
        else:
            self._style("muted")
            self.result.setText("Nothing prepared yet. Choose a receptor and click Prepare receptor and box.")
            self.notes.hide()


# ---------------------------------------------------------------------------------------------------
# ---------------------------------------------------------------------------------------------------
class LigandsPage(Page):
    title = "Ligands"
    blurb = "One ligand per line. Small molecules as 'SMILES name', peptides as 'SEQUENCE name' (2-6 residues, one-letter codes)."

    def __init__(self, win):
        super().__init__(win)

        # Use a horizontal layout to split Form/Table (left) and Viewer (right)
        cols = QHBoxLayout()
        cols.setSpacing(24)

        left = QVBoxLayout()
        left.setSpacing(16)

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
        left.addWidget(self.tabs)

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
        left.addLayout(row)
        left.addWidget(self.count_lbl)

        self.table = QTableWidget()
        self.table.itemSelectionChanged.connect(self._preview_ligand)
        left.addWidget(self.table, 1)

        # --- RIGHT COLUMN: LIGAND VIEWER ---
        right_col = QVBoxLayout()
        right_col.setSpacing(16)

        self.viewer = MolViewer()
        right_col.addWidget(self.viewer, 1)

        cols.addLayout(left, 6)
        cols.addLayout(right_col, 4)
        self.body.addLayout(cols, 1)

        self._counts()

    def _policy(self) -> str:
        return ("warn", "block", "enumerate")[self.policy.currentIndex()]

    def _inputs(self):
        return (ligands.parse_smiles_text(self.small.toPlainText()), ligands.parse_peptide_text(self.pept.toPlainText()))

    def _counts(self):
        s, p = self._inputs()
        t = self.win.run if hasattr(self.win, "run") else None
        if t and t.package:
            lim = rules.tier_limits(t.package)
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

    def _preview_ligand(self):
        """Renders the selected prepared ligand structure in 3D when clicked in the table."""
        w = self.win
        p = w.project if w else None
        sel = self.table.selectionModel().selectedRows() if self.table.selectionModel() else []
        if not p or not sel or not hasattr(self, "viewer"):
            return
        row = sel[0].row()
        item = self.table.item(row, 0)
        if not item:
            return
        lig_name = item.text()

        # Check if the ligand has been prepared and written to disk
        prepared = p.s.get("prepared", [])
        match = next((item for item in prepared if item["ligand"] == lig_name or item["state"] == lig_name), None)
        if match:
            sdf_path = w.run.path / match["sdf"]
            if sdf_path.exists():
                try:
                    self.viewer.load_ligand(sdf_path.read_text(encoding="utf-8"), "sdf")
                except Exception:
                    pass

    def _check(self):
        s, p = self._inputs()
        if not (s or p):
            QMessageBox.information(self, "Ligands", "Add at least one ligand first.")
            return
        self._show_checks(ligands.check_ligands(s + p, self._policy()))

    def _prepare(self):
        w = self.win
        if not w.require_run():
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
# ---------------------------------------------------------------------------------------------------
# ---------------------------------------------------------------------------------------------------
class DockingPage(Page):
    title = "Docking"
    blurb = "Validate the setup by redocking the reference ligand, then dock your ligands with AutoDock Vina."

    def __init__(self, win):
        super().__init__(win)
        cols = QHBoxLayout()
        cols.setSpacing(24)

        left = QVBoxLayout()
        left.setSpacing(16)

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

        grid = QGridLayout()
        grid.setHorizontalSpacing(20)
        grid.setVerticalSpacing(16)
        self.rec_lbl = label("Search depth. Higher is slower and more thorough.", "guide")
        exh_box = QWidget()
        ev = QVBoxLayout(exh_box)
        ev.setContentsMargins(0, 0, 0, 0)
        ev.setSpacing(6)
        ev.addWidget(label("Exhaustiveness", "fieldTitle", False))
        ev.addWidget(self.exh)
        ev.addWidget(self.rec_lbl)
        grid.addWidget(exh_box, 0, 0, Qt.AlignmentFlag.AlignTop)
        grid.addWidget(field("Poses per ligand", self.poses, "How many binding poses Vina keeps for each ligand."), 0, 1, Qt.AlignmentFlag.AlignTop)
        grid.addWidget(field("Energy range (kcal/mol)", self.erange, "Keep poses within this many kcal/mol."), 1, 0, Qt.AlignmentFlag.AlignTop)
        grid.addWidget(field("CPU threads", self.cpu, "Cores Vina may use."), 1, 1, Qt.AlignmentFlag.AlignTop)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        left.addLayout(grid)

        row = QHBoxLayout()
        self.val_btn = button("Run validation (redock reference)", True)
        self.run_btn = button("Run docking")
        self.cancel_btn = button("Cancel", True)
        self.cancel_btn.setEnabled(False)
        self.val_btn.clicked.connect(self._validate)
        self.run_btn.clicked.connect(self._dock)
        self.cancel_btn.clicked.connect(self.win.cancel_job)
        for b_ in (self.val_btn, self.run_btn, self.cancel_btn):
            row.addWidget(b_)
        row.addStretch(1)
        left.addLayout(row)

        self.val_lbl = label("", "summary")
        self.val_lbl.hide()
        left.addWidget(self.val_lbl)

        left.addWidget(label("Progress and Vina output", "h2", False))
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        mono(self.log)
        left.addWidget(self.log, 1)

        # --- RIGHT COLUMN: COMPLEX VIEWER + SETTINGS ---
        right_col = QVBoxLayout()
        right_col.setSpacing(16)

        self.viewer = MolViewer()
        right_col.addWidget(self.viewer, 6)

        set_panel, sv = panel("Viewer Settings")
        self.surf_chk = QCheckBox("Show molecular surface")
        self.cartoon_chk = QCheckBox("Show protein cartoon")
        self.cartoon_chk.setChecked(True)
        self.sticks_chk = QCheckBox("Show ligand sticks")
        self.sticks_chk.setChecked(True)
        for chk in (self.surf_chk, self.cartoon_chk, self.sticks_chk):
            chk.toggled.connect(self._update_viewer_settings)
            sv.addWidget(chk)
        sv.addStretch(1)
        right_col.addWidget(set_panel, 4)

        cols.addLayout(left, 6)
        cols.addLayout(right_col, 5)  # Slightly wider right column
        self.body.addLayout(cols, 1)

    def _update_viewer_settings(self):
        if hasattr(self, "viewer"):
            self.viewer.apply_settings(
                self.surf_chk.isChecked(),
                self.cartoon_chk.isChecked(),
                self.sticks_chk.isChecked()
            )

    def params(self) -> DockParams:
        return DockParams(exhaustiveness=self.exh.value(), num_modes=self.poses.value(), energy_range=self.erange.value(),
                          cpu=self.cpu.value(), ph=rules.docking_defaults()["ph"])

    def append(self, text: str):
        self.log.appendPlainText(text)

    def _validate(self):
        w = self.win
        if not w.require_run():
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
        if not w.require_run():
            return
        proj, params = w.project, self.params()
        if proj.reference_ready and not proj.validation:
            if QMessageBox.question(self, "No validation yet", "The reference ligand has not been redocked yet. "
                                    "Run docking without validation?") != QMessageBox.StandardButton.Yes:
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
            self.rec_lbl.setText(f"Search depth. Recommended for current box: {rec}.")
            if not self._touched and p.receptor_ready and self.exh.value() != rec:
                self.exh.blockSignals(True)
                self.exh.setValue(rec)
                self.exh.blockSignals(False)
        v = p.validation if p else None
        if v:
            self._show_validation(v)
        else:
            self.val_lbl.hide()

        # Load top 1 pose preview into viewer if ready
        if p and p.receptor_ready:
            try:
                rec_path = p.run.path / p.s["receptor"]["protonated_pdb"]
                lig_path = None
                if p.reference_ready:
                    lig_path = p.run.path / p.s["reference"]["sdf"]
                elif p.s.get("prepared"):
                    lig_path = p.run.path / p.s["prepared"][0]["sdf"]

                if rec_path.exists() and lig_path and lig_path.exists():
                    self.viewer.load_complex(
                        rec_path.read_text(encoding="utf-8"),
                        lig_path.read_text(encoding="utf-8"),
                        "pdb", "sdf"
                    )
            except Exception:
                pass


# ---------------------------------------------------------------------------------------------------
class ResultsPage(Page):
    title = "Results"
    blurb = "Ranked by predicted binding affinity. Click any pose to inspect 3D structure or 2D interaction profile."
    HEAD = ["Rank", "Ligand", "Type", "Best state", "Affinity (kcal/mol)", "Est. pKd", "Contact residues", "Polar contacts"]

    def __init__(self, win):
        super().__init__(win)
        self._filling = False

        main_v = QVBoxLayout()
        main_v.setSpacing(12)

        # Viewer and settings stay left; result tables stack in the right column.
        content_row = QHBoxLayout()
        content_row.setSpacing(16)

        viewer_col = QVBoxLayout()
        viewer_col.setSpacing(8)

        v_header_row = QHBoxLayout()
        v_header_row.addWidget(label("Interactive Structural Inspector", "h2", False))
        v_header_row.addStretch(1)
        self.view_mode = QComboBox()
        self.view_mode.addItems(["3D Complex Viewer", "2D Interaction Diagram"])
        self.view_mode.currentIndexChanged.connect(self._load_selected_pose_viewer)
        v_header_row.addWidget(self.view_mode)
        self.export_diagram_btn = button("Export 2D PNG…", True)
        self.export_diagram_btn.setEnabled(False)
        self.export_diagram_btn.clicked.connect(self._export_2d_diagram)
        v_header_row.addWidget(self.export_diagram_btn)
        viewer_col.addLayout(v_header_row)

        self.viewer = MolViewer()
        self.viewer.setMinimumHeight(300)
        self.viewer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        viewer_col.addWidget(self.viewer, 1)

        set_panel, sv = panel("Viewer Settings")
        self.surf_chk = QCheckBox("Show molecular surface")
        self.cartoon_chk = QCheckBox("Show protein cartoon")
        self.cartoon_chk.setChecked(True)
        self.sticks_chk = QCheckBox("Show ligand sticks")
        self.sticks_chk.setChecked(True)
        for chk in (self.surf_chk, self.cartoon_chk, self.sticks_chk):
            chk.toggled.connect(self._update_viewer_settings)
            sv.addWidget(chk)
        sv.addStretch(1)
        set_panel.setMaximumHeight(140)
        viewer_col.addWidget(set_panel)
        content_row.addLayout(viewer_col, 1)

        tables_col = QVBoxLayout()
        tables_col.setSpacing(8)
        tables_col.addWidget(label("Ranked Ligands", "h2", False))
        self.table = QTableWidget()
        self.table.itemChanged.connect(self._on_edit)
        self.table.itemSelectionChanged.connect(self._show_poses)
        self.table.setMinimumHeight(150)
        tables_col.addWidget(self.table, 1)

        self.pose_title = label("Poses", "h2", False)
        tables_col.addWidget(self.pose_title)
        self.pose_table = QTableWidget()
        self.pose_table.verticalHeader().setDefaultSectionSize(22)
        self.pose_table.setMinimumHeight(150)
        self.pose_table.itemSelectionChanged.connect(self._load_selected_pose_viewer)
        tables_col.addWidget(self.pose_table, 1)
        content_row.addLayout(tables_col, 1)

        self.best = label("", "callout")
        self.best.hide()
        main_v.addWidget(self.best)
        main_v.addLayout(content_row, 1)

        self.note = label("Estimated pKd = -dG / (2.303 R T) at 298 K from Vina score.", "muted")
        main_v.addWidget(self.note)

        self.state_lbl = label("", "muted")
        main_v.addWidget(self.state_lbl)

        # Export & Report Action Bar
        act_row = QHBoxLayout()
        self.csv_btn = button("Export CSV…", True)
        self.log_btn = button("Save Vina log…", True)
        self.folder_btn = button("Open results folder", True)
        self.report_type = QComboBox()
        self.report_type.addItems(["Draft (watermarked)", "Final (no watermark)"])
        self.report_btn = button("Generate PDF report")
        self.open_report_btn = button("Open report", True)
        self.csv_btn.clicked.connect(self._export)
        self.log_btn.clicked.connect(self._save_log)
        self.folder_btn.clicked.connect(lambda: self.win.run and open_path(self.win.run.sub("results")))
        self.report_btn.clicked.connect(self._report)
        self.open_report_btn.clicked.connect(self._open_report)
        for b in (self.csv_btn, self.log_btn, self.folder_btn):
            act_row.addWidget(b)
        act_row.addStretch(1)
        act_row.addWidget(self.open_report_btn)
        act_row.addWidget(label("Report type", "muted", False))
        act_row.addWidget(self.report_type)
        act_row.addWidget(self.report_btn)
        main_v.addLayout(act_row)

        self.body.addLayout(main_v, 1)

        self._last_report: Path | None = None
        self._rows: list = []

    def _update_viewer_settings(self):
        if hasattr(self, "viewer"):
            self.viewer.apply_settings(
                self.surf_chk.isChecked(),
                self.cartoon_chk.isChecked(),
                self.sticks_chk.isChecked()
            )

    def _on_edit(self, item):
        if self._filling or item.column() != 1:
            return
        p = self.win.project
        try:
            p.rename_ligand(item.data(Qt.ItemDataRole.UserRole), item.text())
        except Exception as exc:
            QMessageBox.warning(self, "Rename ligand", str(exc))
        self.win.refresh()

    def _export(self):
        p = self.win.project
        if not p or not p.results:
            return
        p.export_results()
        dest, _ = QFileDialog.getSaveFileName(self, "Export results", f"{self.win.run.code}_results.csv", "CSV (*.csv)")
        if dest:
            res = self.win.run.sub("results")
            shutil.copy2(res / "results.csv", dest)
            shutil.copy2(res / "poses.csv", Path(dest).with_name(Path(dest).stem + "_poses.csv"))

    def _save_log(self):
        log = self.win.run.sub("results") / "vina_output.log" if self.win.run else None
        if not log or not log.exists():
            QMessageBox.information(self, "Vina log", "Run docking first.")
            return
        dest, _ = QFileDialog.getSaveFileName(self, "Save Vina log", "vina_output.log", "Log files (*.log)")
        if dest:
            shutil.copy2(log, dest)

    def _report(self):
        w = self.win
        if not w.require_run():
            return
        try:
            self._last_report = generate_report(w.project, w.operator, final=self.report_type.currentIndex() == 1)
        except (ValueError, OSError) as exc:
            QMessageBox.warning(self, "Report", str(exc))
            return
        w.refresh()
        open_path(self._last_report)

    def _open_report(self):
        if self._last_report and self._last_report.exists():
            open_path(self._last_report)
        elif self.win.run:
            open_path(self.win.run.sub("reports"))

    def _show_poses(self):
        p = self.win.project
        sel = self.table.selectionModel().selectedRows() if self.table.selectionModel() else []
        if not p or not self._rows or not sel:
            self.export_diagram_btn.setEnabled(False)
            self.pose_title.setText("Poses")
            fill_table(self.pose_table, ["Pose", "Affinity (kcal/mol)", "Est. pKd", "RMSD l.b. (Å)", "RMSD u.b. (Å)"], [])
            return
        r = self._rows[sel[0].row()]
        from qrksdock.core import thermo
        rows = [[k + 1, f"{a:.2f}", f"{thermo.estimate_pkd(a):.2f}",
                 f"{r.rmsd_lb[k]:.2f}" if k < len(r.rmsd_lb) else "", f"{r.rmsd_ub[k]:.2f}" if k < len(r.rmsd_ub) else ""]
                for k, a in enumerate(r.affinities)]
        self.pose_title.setText(f"Top 10 poses of {p.display_state(r)}")
        fill_table(self.pose_table, ["Pose", "Affinity (kcal/mol)", "Est. pKd", "RMSD l.b. (Å)", "RMSD u.b. (Å)"], rows)

        hh = self.pose_table.horizontalHeader()
        for i in range(self.pose_table.columnCount()):
            hh.setSectionResizeMode(i, QHeaderView.ResizeMode.Stretch)

        if rows:
            self.pose_table.selectRow(0)

    def _load_selected_pose_viewer(self):
        p = self.win.project
        sel_lig = self.table.selectionModel().selectedRows() if self.table.selectionModel() else []
        sel_pose = self.pose_table.selectionModel().selectedRows() if self.pose_table.selectionModel() else []
        can_load = bool(p and sel_lig and sel_pose and p.receptor_ready)
        self.export_diagram_btn.setEnabled(can_load and self.view_mode.currentIndex() == 1)
        if not can_load:
            return

        r = self._rows[sel_lig[0].row()]
        pose_idx = sel_pose[0].row()

        rec_path = p.run.path / p.s["receptor"]["protonated_pdb"]
        pose_path = p.run.path / r.out_pdbqt

        if rec_path.exists() and pose_path.exists():
            try:
                from rdkit import Chem
                from qrksdock.core import contacts
                from qrksdock.core.validation import pose_mol

                mol = pose_mol(pose_path)
                conformer = pose_idx if 0 <= pose_idx < mol.GetNumConformers() else 0
                if self.view_mode.currentIndex() == 1:
                    report = contacts.analyse(rec_path, pose_path, mol, conformer)
                    self.viewer.show_2d_interactions(
                        mol, report.interactions, report.residue_structures, report.thresholds
                    )
                else:
                    pose_text = Chem.MolToMolBlock(mol, confId=conformer)

                    self.viewer.load_complex(
                        rec_path.read_text(encoding="utf-8"),
                        pose_text,
                        "pdb",
                        "sdf",
                        self.surf_chk.isChecked(),
                        self.cartoon_chk.isChecked(),
                        self.sticks_chk.isChecked()
                    )
            except Exception as exc:
                QMessageBox.warning(self, "Pose viewer", str(exc))

    def _export_2d_diagram(self):
        p = self.win.project
        sel_lig = self.table.selectionModel().selectedRows() if self.table.selectionModel() else []
        sel_pose = self.pose_table.selectionModel().selectedRows() if self.pose_table.selectionModel() else []
        if (not self.win.run or not p or not sel_lig or not sel_pose
                or self.view_mode.currentIndex() != 1):
            QMessageBox.information(self, "Export 2D PNG", "Select a pose in the 2D interaction view first.")
            return
        ligand_name = Path(p.display_state(self._rows[sel_lig[0].row()])).name
        pose_number = sel_pose[0].row() + 1
        default_path = self.win.run.sub("results") / (
            f"{self.win.run.code}_{ligand_name}_pose{pose_number}_2D_interaction.png"
        )
        dest, _ = QFileDialog.getSaveFileName(
            self,
            "Export 2D interaction diagram",
            str(default_path),
            "PNG image (*.png)",
        )
        if not dest:
            return
        image_path = Path(dest)
        if image_path.suffix.lower() != ".png":
            image_path = image_path.with_suffix(".png")
        self.export_diagram_btn.setEnabled(False)
        self.viewer.export_2d_png(lambda png: self._finish_2d_diagram_export(png, image_path))

    def _finish_2d_diagram_export(self, png_result: str | None, image_path: Path):
        try:
            self._save_2d_diagram_png(png_result, image_path)
        finally:
            p = self.win.project
            sel_lig = self.table.selectionModel().selectedRows() if self.table.selectionModel() else []
            sel_pose = self.pose_table.selectionModel().selectedRows() if self.pose_table.selectionModel() else []
            self.export_diagram_btn.setEnabled(
                bool(p and p.receptor_ready and sel_lig and sel_pose and self.view_mode.currentIndex() == 1)
            )

    def _save_2d_diagram_png(self, png_result: str | None, image_path: Path):
        if not isinstance(png_result, str) or not png_result:
            QMessageBox.warning(self, "Export 2D PNG", "The current 2D interaction diagram is not ready to export.")
            return
        if png_result.startswith("ERROR: "):
            QMessageBox.warning(self, "Export 2D PNG", png_result.removeprefix("ERROR: "))
            return
        data_url_prefix = "data:image/png;base64,"
        if not png_result.startswith(data_url_prefix):
            QMessageBox.warning(self, "Export 2D PNG", "The diagram exporter returned an invalid image.")
            return
        try:
            png_data = base64.b64decode(png_result[len(data_url_prefix):], validate=True)
        except (binascii.Error, ValueError):
            QMessageBox.warning(self, "Export 2D PNG", "The diagram exporter returned invalid PNG data.")
            return
        image = QImage.fromData(png_data)
        if image.isNull() or image.width() != 1920 or image.height() != 1200:
            QMessageBox.warning(self, "Export 2D PNG", "The exported image has invalid dimensions or data.")
            return
        if not image.save(str(image_path)):
            QMessageBox.warning(self, "Export 2D PNG", f"Could not save the image to:\n{image_path}")
            return
        QMessageBox.information(self, "Export 2D PNG", f"Saved interaction diagram:\n{image_path}")

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

                hh = self.table.horizontalHeader()
                for i in range(self.table.columnCount()):
                    hh.setSectionResizeMode(i, QHeaderView.ResizeMode.Stretch)

                self.state_lbl.setText(f"Run ID {p.s.get('run_id', '')}   |   {w.run.client}   {w.run.code}")
        finally:
            self._filling = False
        if has:
            self.table.selectRow(0)
        self._show_poses()
