"""Round profile pictures: a photo if one exists, otherwise the lead's initials.

Photos are personal data, so they are never stored in the code repository or the installer.
Put a square photo named after the lead's initials (for example LEM.png or LEM.jpg) in the
`avatars` folder inside the QRKSDock settings folder (Help > System check shows where it is).
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPainterPath, QPixmap

from qrksdock import brand, paths

P = brand.ACTIVE
EXTS = (".png", ".jpg", ".jpeg", ".webp")


def avatar_folder() -> Path:
    p = paths.user_data_dir() / "avatars"
    p.mkdir(parents=True, exist_ok=True)
    return p


def find_photo(initials: str) -> Path | None:
    for folder in (avatar_folder(), paths.asset("avatars")):
        for ext in EXTS:
            f = folder / f"{initials}{ext}"
            if f.is_file():
                return f
    return None


def avatar_pixmap(initials: str, size: int = 64) -> QPixmap:
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    painter = QPainter(pm)
    painter.setRenderHint(QPainter.Antialiasing)
    clip = QPainterPath()
    clip.addEllipse(QRectF(0, 0, size, size))
    painter.setClipPath(clip)
    photo = find_photo(initials)
    src = QPixmap(str(photo)) if photo else QPixmap()
    if not src.isNull():
        side = min(src.width(), src.height())                      # centre-crop to a square
        src = src.copy((src.width() - side) // 2, (src.height() - side) // 2, side, side)
        painter.drawPixmap(0, 0, src.scaled(size, size, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation))
    else:
        painter.fillRect(0, 0, size, size, QBrush(QColor(P.blue)))
        font = QFont()
        font.setBold(True)
        font.setPixelSize(int(size * 0.34))
        painter.setFont(font)
        painter.setPen(QColor("white"))
        painter.drawText(QRectF(0, 0, size, size), Qt.AlignCenter, initials)
    painter.end()
    return pm
