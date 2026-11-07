"""Brand styling for the Qt interface."""
from __future__ import annotations

import sys

from PySide6.QtGui import QColor, QFont, QFontDatabase, QIcon, QPainter, QPen, QPixmap
from PySide6.QtCore import Qt

from qrksdock import brand, paths

P = brand.ACTIVE


def load_fonts() -> tuple[str | None, str | None]:
    """Return (body family, display family). None means: use the platform's own system font."""
    mode = brand.FONT_MODE
    if mode == "system" or (mode == "auto" and sys.platform == "darwin"):
        return None, None                                     # macOS: the system font is SF Pro
    body = display = None
    for f in ("Regular", "Medium", "SemiBold", "Bold"):
        fid = QFontDatabase.addApplicationFont(str(paths.asset("fonts", f"Inter-{f}.otf")))
        if fid >= 0:
            body = QFontDatabase.applicationFontFamilies(fid)[0]
    for f in ("SemiBold", "Bold"):
        fid = QFontDatabase.addApplicationFont(str(paths.asset("fonts", f"InterDisplay-{f}.otf")))
        if fid >= 0:
            display = QFontDatabase.applicationFontFamilies(fid)[0]
    return body, display


def base_font(family: str | None) -> QFont:
    f = QFont(family) if family else QFontDatabase.systemFont(QFontDatabase.GeneralFont)
    f.setPointSize(10)
    return f


def apply(app) -> None:
    """Set the typeface and the brand stylesheet on a QApplication."""
    body, display = load_fonts()
    app.setFont(base_font(body))
    app.setStyleSheet(stylesheet(body, display))


def step_icon(done: bool, size: int = 18) -> QIcon:
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    r = size - 4
    if done:
        p.setBrush(QColor(P.blue))
        p.setPen(Qt.NoPen)
        p.drawEllipse(2, 2, r, r)
        pen = QPen(QColor("white"), 1.8)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        p.setPen(pen)
        p.drawLine(int(size * 0.30), int(size * 0.52), int(size * 0.44), int(size * 0.66))
        p.drawLine(int(size * 0.44), int(size * 0.66), int(size * 0.72), int(size * 0.34))
    else:
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(QColor(P.border), 1.6))
        p.drawEllipse(2, 2, r, r)
    p.end()
    return QIcon(pm)


def stylesheet(family: str | None, display: str | None = None) -> str:
    face = f'font-family: "{family}"; ' if family else ""
    heads = (f'QLabel#h1, QLabel#heroTitle, QLabel#loginTitle {{ font-family: "{display}"; }}\n' if display else "")
    return f"""
* {{ {face}color: {P.ink}; }}
{heads}
QMainWindow, QWidget#canvas, QStackedWidget {{ background: {P.canvas}; }}
QFrame#header {{ background: {P.surface}; }}
QFrame#accent {{ background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {P.sky}, stop:1 {P.blue_deep}); min-height: 3px; max-height: 3px; }}
QListWidget#rail {{ background: {P.surface}; border: none; border-right: 1px solid {P.border}; padding: 14px 0; outline: 0; }}
QListWidget#rail::item {{ padding: 11px 16px 11px 14px; border-left: 3px solid transparent; margin: 1px 0; }}
QListWidget#rail::item:selected {{ background: {P.canvas}; border-left: 3px solid {P.blue}; color: {P.blue}; font-weight: 600; }}
QListWidget#rail::item:hover:!selected {{ background: {P.canvas}; }}
QLabel#h1 {{ font-size: 24px; font-weight: 700; color: {P.blue}; }}
QLabel#h2 {{ font-size: 13px; font-weight: 600; color: {P.ink}; }}
QLabel#muted {{ color: {P.muted}; }}
QLabel#chip {{ background: {P.canvas}; border: 1px solid {P.border}; border-radius: 4px; padding: 2px 8px; color: {P.muted}; }}
QLabel#chipOk {{ background: #E5F5EE; border: 1px solid #B6E1CD; border-radius: 4px; padding: 2px 8px; color: {P.ok}; font-weight: 600; }}
QLabel#callout {{ background: #FDF1C9; border-left: 4px solid {P.yellow}; padding: 12px 16px; font-size: 14px; font-weight: 600; }}
QLabel#summary {{ background: {P.surface}; border: 1px solid {P.border}; border-left: 4px solid {P.blue}; border-radius: 4px; padding: 10px 14px; }}
QLabel#summaryOk {{ background: #F1FAF6; border: 1px solid #B6E1CD; border-left: 4px solid {P.ok}; border-radius: 4px; padding: 10px 14px; }}
QLabel#summaryBad {{ background: #FDF1EF; border: 1px solid #F0C4BE; border-left: 4px solid {P.danger}; border-radius: 4px; padding: 10px 14px; }}
QLabel#warn {{ background: #FFF6E0; border-left: 4px solid {P.warn}; padding: 8px 12px; }}
QPushButton {{ background: {P.blue}; color: white; border: none; border-radius: 6px; padding: 10px 20px; font-weight: 600; min-height: 22px; }}
QPushButton:hover {{ background: {P.blue_deep}; }}
QPushButton:pressed {{ background: {P.ink}; }}
QPushButton:disabled {{ background: {P.border}; color: {P.muted}; }}
QPushButton#secondary {{ background: {P.surface}; color: {P.blue}; border: 1px solid {P.border}; }}
QPushButton#secondary:hover {{ border-color: {P.blue}; }}
QPushButton#secondary:disabled {{ background: {P.canvas}; color: {P.muted}; border-color: {P.border}; }}
QLineEdit, QPlainTextEdit, QSpinBox, QDoubleSpinBox, QComboBox, QTableWidget, QListWidget#plain {{
    background: {P.surface}; border: 1px solid {P.border}; border-radius: 6px; padding: 8px 12px; min-height: 22px; selection-background-color: #D9E8FB; selection-color: {P.ink}; }}
QSpinBox, QDoubleSpinBox {{ min-width: 96px; }}
QLineEdit:focus, QPlainTextEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {{ border: 1px solid {P.blue}; }}
QComboBox QAbstractItemView {{ background: {P.surface}; selection-background-color: {P.canvas}; selection-color: {P.blue}; border: 1px solid {P.border}; }}
QSpinBox::up-button, QSpinBox::down-button, QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{ width: 0; border: none; }}
QTableWidget {{ gridline-color: transparent; alternate-background-color: {P.canvas}; padding: 0; }}
QTableWidget::item:selected {{ background: #D9E8FB; color: {P.ink}; }}
QHeaderView::section {{ background: {P.canvas}; border: none; border-bottom: 1px solid {P.border}; padding: 7px 8px; font-weight: 600; color: {P.muted}; }}
QTabWidget::pane {{ border: 1px solid {P.border}; border-radius: 4px; background: {P.surface}; top: -1px; }}
QTabBar::tab {{ background: transparent; padding: 8px 16px; border: none; color: {P.muted}; }}
QTabBar::tab:selected {{ color: {P.blue}; border-bottom: 2px solid {P.blue}; font-weight: 600; }}
QProgressBar {{ background: {P.border}; border: none; border-radius: 4px; max-height: 8px; min-height: 8px; text-align: center; color: transparent; }}
QProgressBar::chunk {{ background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {P.sky}, stop:1 {P.blue}); border-radius: 4px; }}
QStatusBar {{ background: {P.surface}; border-top: 1px solid {P.border}; }}
QMenuBar {{ background: {P.surface}; }}
QMenuBar::item:selected {{ background: {P.canvas}; }}
QMenu {{ background: {P.surface}; border: 1px solid {P.border}; }}
QMenu::item:selected {{ background: {P.canvas}; color: {P.blue}; }}
QRadioButton, QCheckBox {{ spacing: 8px; }}
QScrollArea {{ border: none; background: transparent; }}
QToolTip {{ background: {P.ink}; color: white; border: none; padding: 5px; }}
QLabel#fieldTitle {{ font-weight: 600; font-size: 13px; }}
QLabel#guide {{ color: {P.muted}; font-size: 12px; }}
QLabel#error {{ background: #FDF1EF; border-left: 4px solid {P.danger}; border-radius: 4px; padding: 8px 12px; color: {P.danger}; }}
QLabel#userName {{ font-weight: 600; }}
QPushButton#ghost {{ background: transparent; color: {P.muted}; border: 1px solid {P.border}; padding: 7px 14px; }}
QPushButton#ghost:hover {{ color: {P.blue}; border-color: {P.blue}; }}
QFrame#loginHero {{ background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {P.sky}, stop:1 {P.blue_deep}); }}
QFrame#loginHero QLabel {{ color: white; background: transparent; }}
QLabel#heroTitle {{ font-size: 44px; font-weight: 700; }}
QLabel#heroSub {{ font-size: 17px; }}
QLabel#heroFoot {{ font-size: 12px; color: rgba(255,255,255,0.8); }}
QLabel#loginTitle {{ font-size: 30px; font-weight: 700; }}
QToolButton#tile {{ background: {P.surface}; border: 1px solid {P.border}; border-radius: 10px; padding: 14px 8px; color: {P.ink}; font-size: 12px; }}
QToolButton#tile:hover {{ border-color: {P.blue}; }}
QToolButton#tile:checked {{ border: 2px solid {P.blue}; background: #F0F6FE; }}
"""
