import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
DATA = Path(__file__).parent / "data"


@pytest.fixture(scope="session")
def data():
    return DATA


@pytest.fixture(scope="session")
def vina_exe():
    from qrksdock.core import vina_runner
    exe = vina_runner.find_vina()
    if exe is None:
        pytest.skip("Vina executable not found (run scripts/fetch_vina.py)")
    return exe


slow = pytest.mark.skipif(os.environ.get("QRKS_SLOW") != "1", reason="set QRKS_SLOW=1 to run long docking tests")


@pytest.fixture(autouse=True)
def isolated_user_data(tmp_path, monkeypatch):
    """Tests never touch the real settings folder, saved passwords, or Qt settings."""
    from qrksdock import paths
    d = tmp_path / "appdata"
    d.mkdir()
    monkeypatch.setattr(paths, "user_data_dir", lambda: d)
    try:
        from PySide6.QtCore import QSettings
        QSettings.setDefaultFormat(QSettings.IniFormat)
        QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, str(d / "qt"))
    except ImportError:
        pass
    return d
