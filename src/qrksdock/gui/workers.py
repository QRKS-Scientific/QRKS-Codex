"""Run long jobs off the interface thread so the window never freezes."""
from __future__ import annotations

import threading
from typing import Any, Callable

from PySide6.QtCore import QThread, Signal

from qrksdock.core.pipeline import Cancelled


def friendly(exc: Exception) -> str:
    return f"{exc}" or exc.__class__.__name__


class Worker(QThread):
    log = Signal(str)
    progress = Signal(float, str)
    done = Signal(object)
    failed = Signal(str)
    cancelled = Signal()

    def __init__(self, fn: Callable[[Callable[[str], None], Callable[[float, str], None], threading.Event], Any], parent=None):
        super().__init__(parent)
        self.fn = fn
        self.cancel_event = threading.Event()

    def run(self) -> None:
        try:
            result = self.fn(self.log.emit, lambda f, m: self.progress.emit(f, m), self.cancel_event)
            self.done.emit(result)
        except Cancelled:
            self.cancelled.emit()
        except Exception as exc:                                    # noqa: BLE001
            self.failed.emit(friendly(exc))
