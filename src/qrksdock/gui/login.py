"""Sign-in screen. Progressive two-step email -> profile + password flow."""
from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, Qt, QTimer, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QDialog, QFormLayout, QFrame, QGraphicsOpacityEffect, QHBoxLayout,
                               QLabel, QLineEdit, QPushButton, QVBoxLayout, QWidget)

from qrksdock import __version__, brand, paths
from qrksdock.core import accounts as acc
from qrksdock.gui.avatars import avatar_pixmap
from qrksdock.gui.pages import button, label


def _account_email(account: dict[str, str]) -> str:
    return (account.get("email") or f"{account['initials'].lower()}@qrks.com").lower()


class ChangePasswordDialog(QDialog):
    """Shown when a temporary password must be replaced."""

    def __init__(self, store: acc.AccountStore, identifier: str, current_password: str, parent=None):
        super().__init__(parent)
        self.store, self.identifier, self.current = store, identifier, current_password
        self.setWindowTitle("Choose your password")
        self.setModal(True)
        self.setMinimumWidth(460)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 24, 28, 24)
        lay.setSpacing(12)
        lay.addWidget(label("Choose your own password", "h2"))
        lay.addWidget(label(f"You signed in with a temporary password. Choose a new one for {identifier}. "
                            f"Use at least {acc.MIN_PASSWORD_LENGTH} characters.", "muted"))
        form = QFormLayout()
        form.setVerticalSpacing(10)
        self.new = QLineEdit()
        self.new.setEchoMode(QLineEdit.EchoMode.Password)
        self.again = QLineEdit()
        self.again.setEchoMode(QLineEdit.EchoMode.Password)
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
            self.store.change_password(self.identifier, self.current, self.new.text())
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
        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._tick)
        self._locked_for = 0
        self._fade_anim: QPropertyAnimation | None = None

        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(self._hero(), 4)
        outer.addWidget(self._form(), 5)
        self.email.setFocus()

    # ---- left: brand panel ------------------------------------------------------------------------
    def _hero(self) -> QFrame:
        hero = QFrame()
        hero.setObjectName("loginHero")
        hero.setMinimumWidth(320)
        v = QVBoxLayout(hero)
        v.setContentsMargins(56, 48, 56, 40)
        v.addStretch(2)
        mark = QLabel()
        mark.setPixmap(QPixmap(str(paths.asset("logos", "brandmark_white.png"))).scaledToHeight(
            112, Qt.TransformationMode.SmoothTransformation))
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

    # ---- right: two-step email -> profile + password form -----------------------------------------
    def _form(self) -> QWidget:
        wrap = QWidget()
        wrap.setObjectName("canvas")
        h = QHBoxLayout(wrap)
        h.addStretch(1)
        col = QWidget()
        col.setObjectName("canvas")
        col.setMinimumWidth(460)
        col.setMaximumWidth(560)
        v = QVBoxLayout(col)
        v.setContentsMargins(24, 40, 24, 32)
        v.setSpacing(12)
        v.addStretch(1)

        t = QLabel("Sign in")
        t.setObjectName("loginTitle")
        v.addWidget(t)
        self.subtitle = label("Enter your QRKS email to continue.", "muted")
        v.addWidget(self.subtitle)
        v.addSpacing(10)

        # ---- Step 1: Email input container --------------------------------------------------------
        self.email_step = QWidget()
        e_lay = QVBoxLayout(self.email_step)
        e_lay.setContentsMargins(0, 0, 0, 0)
        e_lay.setSpacing(10)
        e_lay.addWidget(label("Email", "fieldTitle", False))
        self.email = QLineEdit()
        self.email.setPlaceholderText("name@qrks.com")
        self.email.textChanged.connect(self._on_email_changed)
        self.email.returnPressed.connect(self._advance_to_password)
        e_lay.addWidget(self.email)
        e_lay.addSpacing(4)
        self.next_btn = button("Continue")
        self.next_btn.setEnabled(False)
        self.next_btn.clicked.connect(self._advance_to_password)
        e_lay.addWidget(self.next_btn)
        v.addWidget(self.email_step)

        # ---- Step 2: Profile card + Password pop-up container -------------------------------------
        self.auth_step = QWidget()
        a_lay = QVBoxLayout(self.auth_step)
        a_lay.setContentsMargins(0, 0, 0, 0)
        a_lay.setSpacing(12)

        # Profile card
        self.profile_card = QFrame()
        self.profile_card.setObjectName("tile")
        self.profile_card.setStyleSheet(
            "QFrame#tile { background: #F8FAFC; border: 1px solid #CBD5E1; border-radius: 10px; }"
        )
        card_row = QHBoxLayout(self.profile_card)
        card_row.setContentsMargins(14, 12, 14, 12)
        card_row.setSpacing(14)

        self.avatar_lbl = QLabel()
        self.avatar_lbl.setFixedSize(52, 52)
        card_row.addWidget(self.avatar_lbl)

        info_col = QVBoxLayout()
        info_col.setSpacing(2)
        self.name_lbl = label("", "fieldTitle", False)
        self.role_lbl = label("", "muted")
        self.email_lbl = label("", "guide")
        info_col.addWidget(self.name_lbl)
        info_col.addWidget(self.role_lbl)
        info_col.addWidget(self.email_lbl)
        card_row.addLayout(info_col, 1)

        self.change_btn = QPushButton("Change")
        self.change_btn.setObjectName("ghost")
        self.change_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.change_btn.clicked.connect(self._back_to_email)
        card_row.addWidget(self.change_btn, 0, Qt.AlignmentFlag.AlignVCenter)

        a_lay.addWidget(self.profile_card)

        # Password row
        a_lay.addWidget(label("Password", "fieldTitle", False))
        pw_row = QHBoxLayout()
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.password.setPlaceholderText("Enter your password")
        self.password.textChanged.connect(self._on_password_changed)
        self.password.returnPressed.connect(self._submit)
        self.show_btn = QPushButton("Show")
        self.show_btn.setObjectName("ghost")
        self.show_btn.setCheckable(True)
        self.show_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.show_btn.toggled.connect(lambda on: (
            self.password.setEchoMode(QLineEdit.EchoMode.Normal if on else QLineEdit.EchoMode.Password),
                                                  self.show_btn.setText("Hide" if on else "Show")))
        pw_row.addWidget(self.password, 1)
        pw_row.addWidget(self.show_btn)
        a_lay.addLayout(pw_row)

        self.go = button("Sign in")
        self.go.clicked.connect(self._submit)
        self.go.setEnabled(False)
        a_lay.addWidget(self.go)

        self._opacity = QGraphicsOpacityEffect(self.auth_step)
        self._opacity.setOpacity(1.0)
        self.auth_step.setGraphicsEffect(self._opacity)
        self.auth_step.hide()
        v.addWidget(self.auth_step)

        self.msg = label("", "error")
        self.msg.hide()
        v.addWidget(self.msg)
        if not self.store.accounts():
            self._error("No accounts were found in this installation, so nobody can sign in. "
                        "Reinstall the app, or ask the Technical Lead for a new build.")

        v.addSpacing(8)
        v.addWidget(label("Accounts are issued by the Technical Lead. There is no sign-up. "
                          "If you forget your password, ask the Technical Lead to reset it.", "guide"))
        if hasattr(self.store, "describe"):
            v.addWidget(label(self.store.describe(), "guide"))
        v.addStretch(2)
        h.addWidget(col, 1)
        h.addStretch(1)
        return wrap

    # ---- step transitions & behaviour -------------------------------------------------------------
    def _is_valid_email(self) -> bool:
        email = self.email.text().strip()
        if "@" not in email:
            return False
        local, _, domain = email.partition("@")
        return bool(local) and "." in domain and not domain.startswith(".") and not domain.endswith(".")

    def _on_email_changed(self) -> None:
        self.next_btn.setEnabled(self._is_valid_email())

    def _on_password_changed(self) -> None:
        self.msg.hide()
        self.go.setEnabled(bool(self.password.text()) and self._locked_for == 0)

    def _advance_to_password(self) -> None:
        if not self._is_valid_email():
            return
        clean_email = self.email.text().strip().lower()
        matched = next((a for a in self.store.accounts() if _account_email(a) == clean_email), None)

        if matched:
            initials = matched["initials"]
            display_name = matched.get("display_name") or matched.get("name", initials)
            role = matched.get("role", "QRKS Scientific")
        else:
            initials = clean_email.split("@")[0].upper()[:3]
            display_name = clean_email.split("@")[0].upper()
            role = "QRKS Scientific"

        self.avatar_lbl.setPixmap(avatar_pixmap(initials, 52))
        self.name_lbl.setText(display_name)
        self.role_lbl.setText(role)
        self.email_lbl.setText(clean_email)

        self.subtitle.setText("Confirm your profile and enter your password.")
        self.email_step.hide()
        self.password.clear()
        self.show_btn.setChecked(False)
        self.msg.hide()
        self.go.setEnabled(False)

        self.auth_step.show()
        self._fade_anim = QPropertyAnimation(self._opacity, b"opacity", self)
        self._fade_anim.setDuration(220)
        self._fade_anim.setStartValue(0.0)
        self._fade_anim.setEndValue(1.0)
        self._fade_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._fade_anim.start()

        self.password.setFocus()

    def _back_to_email(self) -> None:
        self.auth_step.hide()
        self.msg.hide()
        self.password.clear()
        self.subtitle.setText("Enter your QRKS email to continue.")
        self.email_step.show()
        self.email.setFocus()
        self.email.selectAll()

    def reset(self) -> None:
        """Called after sign-out: return to Step 1 with empty email and password."""
        self.email.clear()
        self.password.clear()
        self.show_btn.setChecked(False)
        self.msg.hide()
        self._timer.stop()
        self._locked_for = 0
        self.next_btn.setEnabled(False)
        self.go.setEnabled(False)
        self.auth_step.hide()
        self.subtitle.setText("Enter your QRKS email to continue.")
        self.email_step.show()
        self.email.setFocus()

    def _error(self, text: str) -> None:
        self.msg.setText(text)
        self.msg.show()

    def _tick(self) -> None:
        self._locked_for -= 1
        if self._locked_for <= 0:
            self._timer.stop()
            self._locked_for = 0
            self.go.setEnabled(bool(self.password.text()))
            self.msg.hide()
        else:
            self._error(f"Too many wrong passwords. Try again in {self._locked_for} s.")

    def _submit(self) -> None:
        if not self._is_valid_email() or not self.password.text() or self._locked_for:
            return
        email = self.email.text().strip()
        pw = self.password.text()
        result = self.store.authenticate(email, pw)
        if not result.ok:
            self.password.selectAll()
            self._error(result.message)
            if result.locked_for:
                self._locked_for = result.locked_for
                self.go.setEnabled(False)
                self._timer.start()
            return
        if result.must_change:
            dlg = ChangePasswordDialog(self.store, email, pw, self)
            if dlg.exec() != QDialog.DialogCode.Accepted:
                self._error("You need to choose your own password before you can continue.")
                return
        matched = next((a for a in self.store.accounts() if _account_email(a) == email.lower()), None)
        initials = matched["initials"] if matched else email.split("@")[0].upper()
        self.msg.hide()
        self.email.clear()
        self.password.clear()
        self.signedIn.emit(initials)