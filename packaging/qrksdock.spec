# -*- mode: python ; coding: utf-8 -*-
# Build with:  pyinstaller packaging/qrksdock.spec --noconfirm
# Produces dist/QRKSDock/ (Windows, Linux) and dist/QRKSDock.app (macOS).
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules, copy_metadata

ROOT = Path(SPECPATH).parent
import re
VERSION = re.search(r'__version__\s*=\s*"([^"]+)"', (ROOT / "src" / "qrksdock" / "__init__.py").read_text()).group(1)

datas = [(str(ROOT / "assets"), "assets"),
         (str(ROOT / "src" / "qrksdock" / "data"), "qrksdock_data")]      # rules.json AND accounts.json
vina = [p for p in (ROOT / "bin").glob("vina*") if p.is_file()]
if not vina:
    raise SystemExit("bin/vina is missing. Run: python scripts/fetch_vina.py")
datas += [(str(p), "bin") for p in vina]

for pkg in ("pdb2pqr", "propka", "meeko", "molscrub", "reportlab"):
    datas += collect_data_files(pkg)
for dist in ("meeko", "molscrub", "pdb2pqr", "propka", "rdkit", "reportlab", "PySide6-Essentials", "keyring"):
    try:
        datas += copy_metadata(dist)
    except Exception:
        pass

hidden = []
for pkg in ("meeko", "molscrub", "pdb2pqr", "propka", "qrksdock", "keyring", "win32ctypes", "jaraco", "httpx", "httpcore", "anyio", "certifi"):
    try:                                    # win32ctypes exists only on Windows, so a missing package is fine
        hidden += collect_submodules(pkg)
    except Exception:
        pass
datas += collect_data_files("certifi")

a = Analysis([str(ROOT / "packaging" / "entry.py")], pathex=[str(ROOT / "src")], datas=datas,
             hiddenimports=hidden, excludes=["tkinter", "matplotlib", "IPython", "pytest",
                                              "PySide6.QtQml", "PySide6.QtQuick", "PySide6.Qt3DCore"],
             noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="QRKSDock", console=False,
          icon=str(ROOT / "assets" / "icons" / ("qrksdock.ico" if sys.platform == "win32" else "qrksdock.icns")),
          disable_windowed_traceback=False)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="QRKSDock")
if sys.platform == "darwin":
    app = BUNDLE(coll, name="QRKSDock.app", icon=str(ROOT / "assets" / "icons" / "qrksdock.icns"),
                 bundle_identifier="com.qrksscientific.qrksdock",
                 info_plist={"CFBundleName": "QRKSDock", "CFBundleDisplayName": "QRKSDock",
                             "CFBundleShortVersionString": VERSION, "NSHighResolutionCapable": True,
                             "LSMinimumSystemVersion": "14.0"})
