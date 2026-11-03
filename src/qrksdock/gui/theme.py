"""Brand styling for the Qt interface."""
from __future__ import annotations

from PySide6.QtGui import QColor, QFont, QFontDatabase, QIcon, QPainter, QPen, QPixmap
from PySide6.QtCore import Qt

from qrksdock import brand, paths

P = brand.ACTIVE


def load_fonts() -> str:
    family = "Sans Serif"
    for f in ("Regular", "Medium", "SemiBold", "Bold"):
        fid = QFontDatabase.addApplicationFont(str(paths.asset("fonts", f"Montserrat-{f}.ttf")))
        if fid >= 0:
            family = QFontDatabase.applicationFontFamilies(fid)[0]
    return family if family != "Sans Serif" else brand.FONT_FAMILY


def base_font(family: str) -> QFont:
    f = QFont(family)
    f.setPointSize(10)
    return f


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


def stylesheet(family: str) -> str:
    return f"""
* {{ font-family: "{family}"; color: {P.ink}; }}
QMainWindow, QWidget#canvas, QStackedWidget {{ background: {P.canvas}; }}
QFrame#header {{ background: {P.surface}; }}
QFrame#accent {{ background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {P.sky}, stop:1 {P.blue_deep}); min-height: 3px; max-height: 3px; }}
QListWidget#rail {{ background: {P.surface}; border: none; border-right: 1px solid {P.border}; padding: 14px 0; outline: 0; }}
QListWidget#rail::item {{ padding: 11px 16px 11px 14px; border-left: 3px solid transparent; margin: 1px 0; }}
QListWidget#rail::item:selected {{ background: {P.canvas}; border-left: 3px solid {P.blue}; color: {P.blue}; font-weight: 600; }}
QListWidget#rail::item:hover:!selected {{ background: {P.canvas}; }}
QLabel#h1 {{ font-size: 19px; font-weight: 700; color: {P.blue}; }}
QLabel#h2 {{ font-size: 13px; font-weight: 600; color: {P.ink}; }}
QLabel#muted {{ color: {P.muted}; }}
QLabel#chip {{ background: {P.canvas}; border: 1px solid {P.border}; border-radius: 4px; padding: 2px 8px; color: {P.muted}; }}
QLabel#chipOk {{ background: #E5F5EE; border: 1px solid #B6E1CD; border-radius: 4px; padding: 2px 8px; color: {P.ok}; font-weight: 600; }}
QLabel#callout {{ background: #FDF1C9; border-left: 4px solid {P.yellow}; padding: 12px 16px; font-size: 14px; font-weight: 600; }}
QLabel#summary {{ background: {P.surface}; border: 1px solid {P.border}; border-left: 4px solid {P.blue}; border-radius: 4px; padding: 10px 14px; }}
QLabel#summaryOk {{ background: #F1FAF6; border: 1px solid #B6E1CD; border-left: 4px solid {P.ok}; border-radius: 4px; padding: 10px 14px; }}
QLabel#summaryBad {{ background: #FDF1EF; border: 1px solid #F0C4BE; border-left: 4px solid {P.danger}; border-radius: 4px; padding: 10px 14px; }}
QLabel#warn {{ background: #FFF6E0; border-left: 4px solid {P.warn}; padding: 8px 12px; }}
QPushButton {{ background: {P.blue}; color: white; border: none; border-radius: 4px; padding: 8px 16px; font-weight: 600; }}
QPushButton:hover {{ background: {P.blue_deep}; }}
QPushButton:pressed {{ background: {P.ink}; }}
QPushButton:disabled {{ background: {P.border}; color: {P.muted}; }}
QPushButton#secondary {{ background: {P.surface}; color: {P.blue}; border: 1px solid {P.border}; }}
QPushButton#secondary:hover {{ border-color: {P.blue}; }}
QPushButton#secondary:disabled {{ background: {P.canvas}; color: {P.muted}; border-color: {P.border}; }}
QLineEdit, QPlainTextEdit, QSpinBox, QDoubleSpinBox, QComboBox, QTableWidget, QListWidget#plain {{
    background: {P.surface}; border: 1px solid {P.border}; border-radius: 4px; padding: 5px 8px; selection-background-color: {P.sky}; selection-color: white; }}
QLineEdit:focus, QPlainTextEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {{ border: 1px solid {P.blue}; }}
QComboBox QAbstractItemView {{ background: {P.surface}; selection-background-color: {P.canvas}; selection-color: {P.blue}; border: 1px solid {P.border}; }}
QSpinBox::up-button, QSpinBox::down-button, QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{ width: 0; border: none; }}
QTableWidget {{ gridline-color: transparent; alternate-background-color: {P.canvas}; padding: 0; }}
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
"""
