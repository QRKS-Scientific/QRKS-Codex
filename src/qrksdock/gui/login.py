"""Sign-in screen. Six pre-made accounts, no registration."""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (QButtonGroup, QDialog, QFormLayout, QFrame, QGridLayout, QHBoxLayout, QLabel,
                               QLineEdit, QPushButton, QToolButton, QVBoxLayout, QWidget)

from qrksdock import __version__, brand, paths
from qrksdock.core import accounts as acc
from qrksdock.gui.avatars import avatar_pixmap
from qrksdock.gui.pages import button, label


class ChangePasswordDialog(QDialog):
    """Shown at a lead's first sign-in on a laptop: the temporary password must be replaced."""

    def __init__(self, store: acc.AccountStore, initials: str, current_password: str, parent=None):
        super().__init__(parent)
        self.store, self.initials, self.current = store, initials, current_password
        self.setWindowTitle("Choose your password")
        self.setModal(True)
        self.setMinimumWidth(460)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 24, 28, 24)
        lay.setSpacing(12)
        lay.addWidget(label("Choose your own password", "h2"))
        lay.addWidget(label(f"You signed in with a temporary password. Choose a new one for {initials} on this laptop. "
                            f"Use at least {acc.MIN_PASSWORD_LENGTH} characters.", "muted"))
        form = QFormLayout()
        form.setVerticalSpacing(10)
        self.new = QLineEdit()
        self.new.setEchoMode(QLineEdit.Password)
        self.again = QLineEdit()
        self.again.setEchoMode(QLineEdit.Password)
        form.addRow("New password", self.new)
        form.addRow("Repeat it", self.again)
        lay.addLayout(form)
        self.msg = label("", "error")
        self.msg.hide()
        lay.addWidget(self.msg)
        row = QHBoxLayout()
        cancel = button("Cancel", True)
        save = button("Save password")
        cancel.clicked.connect(self.reject)
        save.clicked.connect(self._save)
        self.again.returnPressed.connect(self._save)
        row.addStretch(1)
        row.addWidget(cancel)
        row.addWidget(save)
        lay.addLayout(row)

    def _save(self) -> None:
        if self.new.text() != self.again.text():
            return self._error("The two passwords do not match.")
        try:
            self.store.change_password(self.initials, self.current, self.new.text())
        except ValueError as exc:
            return self._error(str(exc))
        self.accept()

    def _error(self, text: str) -> None:
        self.msg.setText(text)
        self.msg.show()


class LoginPage(QWidget):
    signedIn = Signal(str)                       # initials of the lead who signed in

    def __init__(self, store: acc.AccountStore, last_user: str = "", parent=None):
        super().__init__(parent)
        self.setObjectName("canvas")
        self.store = store
        self.selected = ""
        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._tick)
        self._locked_for = 0

        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(self._hero(), 4)
        outer.addWidget(self._form(), 5)
        if last_user and any(a["initials"] == last_user for a in self.store.accounts()):
            self._select(last_user)

    # ---- left: brand panel ------------------------------------------------------------------------
    def _hero(self) -> QFrame:
        hero = QFrame()
        hero.setObjectName("loginHero")
        hero.setMinimumWidth(320)
        v = QVBoxLayout(hero)
        v.setContentsMargins(56, 48, 56, 40)
        v.addStretch(2)
        mark = QLabel()
        mark.setPixmap(QPixmap(str(paths.asset("logos", "brandmark_white.png"))).scaledToHeight(112, Qt.SmoothTransformation))
        v.addWidget(mark)
        v.addSpacing(26)
        title = QLabel("QRKSDock")
        title.setObjectName("heroTitle")
        v.addWidget(title)
        sub = QLabel("Protein-ligand docking for QRKS Scientific")
        sub.setObjectName("heroSub")
        sub.setWordWrap(True)
        v.addWidget(sub)
        v.addSpacing(10)
        tag = QLabel(brand.TAGLINE)
        tag.setObjectName("heroSub")
        v.addWidget(tag)
        v.addStretch(3)
        foot = QLabel(f"QRKS Scientific  |  Version {__version__}")
        foot.setObjectName("heroFoot")
        v.addWidget(foot)
        return hero

    # ---- right: account tiles and password ---------------------------------------------------------------
    def _form(self) -> QWidget:
        wrap = QWidget()
        wrap.setObjectName("canvas")
        h = QHBoxLayout(wrap)
        h.addStretch(1)
        col = QWidget()
        col.setObjectName("canvas")
        col.setMinimumWidth(640)
        col.setMaximumWidth(800)
        v = QVBoxLayout(col)
        v.setContentsMargins(24, 40, 24, 32)
        v.setSpacing(14)
        v.addStretch(1)
        t = QLabel("Sign in")
        t.setObjectName("loginTitle")
        v.addWidget(t)
        v.addWidget(label("Choose your account, then enter your password.", "muted"))
        v.addSpacing(6)

        grid = QGridLayout()
        grid.setSpacing(12)
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        self.tiles: dict[str, QToolButton] = {}
        for i, a in enumerate(self.store.accounts()):
            tile = QToolButton()
            tile.setObjectName("tile")
            tile.setCheckable(True)
            tile.setCursor(Qt.PointingHandCursor)
            tile.setIcon(QIcon(avatar_pixmap(a["initials"], 96)))
            tile.setIconSize(QSize(64, 64))
            tile.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
            tile.setText(f"{a['display_name']}\n{a['role']}")
            tile.setMinimumSize(196, 150)
            tile.clicked.connect(lambda _=False, ini=a["initials"]: self._select(ini))
            self.group.addButton(tile)
            self.tiles[a["initials"]] = tile
            grid.addWidget(tile, i // 3, i % 3)
        v.addLayout(grid)
        v.addSpacing(8)

        self.who = label("", "fieldTitle", False)
        v.addWidget(self.who)
        row = QHBoxLayout()
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.Password)
        self.password.setPlaceholderText("Password")
        self.password.returnPressed.connect(self._submit)
        self.show_btn = QPushButton("Show")
        self.show_btn.setObjectName("ghost")
        self.show_btn.setCheckable(True)
        self.show_btn.setCursor(Qt.PointingHandCursor)
        self.show_btn.toggled.connect(lambda on: (self.password.setEchoMode(QLineEdit.Normal if on else QLineEdit.Password),
                                                  self.show_btn.setText("Hide" if on else "Show")))
        row.addWidget(self.password, 1)
        row.addWidget(self.show_btn)
        v.addLayout(row)
        self.msg = label("", "error")
        self.msg.hide()
        v.addWidget(self.msg)
        if not self.store.accounts():
            self._error("No accounts were found in this installation, so nobody can sign in. "
                        "Reinstall the app, or ask the Technical Lead for a new build.")
        self.go = button("Sign in")
        self.go.clicked.connect(self._submit)
        self.go.setEnabled(False)
        v.addWidget(self.go)
        v.addSpacing(6)
        v.addWidget(label("Accounts are issued by the Technical Lead. There is no sign-up. "
                          "If you forget your password, ask the Technical Lead for a new temporary one.", "guide"))
        if hasattr(self.store, "describe"):
            v.addWidget(label(self.store.describe(), "guide"))
        v.addStretch(2)
        h.addWidget(col, 1)
        h.addStretch(1)
        return wrap

    # ---- behaviour ---------------------------------------------------------------------------------------
    def _select(self, initials: str) -> None:
        self.selected = initials
        self.tiles[initials].setChecked(True)
        person = next(a for a in self.store.accounts() if a["initials"] == initials)
        self.who.setText(f"Password for {person['display_name']}")
        self.go.setEnabled(self._locked_for == 0)
        self.msg.hide()
        self.password.clear()
        self.password.setFocus()

    def reset(self) -> None:
        """Called after sign-out: clear the password but keep the tile choice."""
        self.password.clear()
        self.show_btn.setChecked(False)
        self.msg.hide()
        self._timer.stop()
        self._locked_for = 0
        self.go.setEnabled(bool(self.selected))
        self.password.setFocus()

    def _error(self, text: str) -> None:
        self.msg.setText(text)
        self.msg.show()

    def _tick(self) -> None:
        self._locked_for -= 1
        if self._locked_for <= 0:
            self._timer.stop()
            self._locked_for = 0
            self.go.setEnabled(bool(self.selected))
            self.msg.hide()
        else:
            self._error(f"Too many wrong passwords. Try again in {self._locked_for} s.")

    def _submit(self) -> None:
        if not self.selected or self._locked_for:
            return
        pw = self.password.text()
        result = self.store.authenticate(self.selected, pw)
        if not result.ok:
            self.password.selectAll()
            self._error(result.message)
            if result.locked_for:
                self._locked_for = result.locked_for
                self.go.setEnabled(False)
                self._timer.start()
            return
        if result.must_change:
            dlg = ChangePasswordDialog(self.store, self.selected, pw, self)
            if dlg.exec() != QDialog.Accepted:
                self._error("You need to choose your own password before you can continue.")
                return
        self.msg.hide()
        self.password.clear()
        self.signedIn.emit(self.selected)
