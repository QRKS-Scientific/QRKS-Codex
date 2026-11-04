"""Download the official AutoDock Vina executable for this platform into bin/.

The download is verified against pinned SHA-256 checksums, so a tampered or corrupted
file is rejected before it can be bundled into the app.

    python scripts/fetch_vina.py            # picks the right build for this machine
    python scripts/fetch_vina.py --force    # re-download
"""
from __future__ import annotations

import argparse
import hashlib
import platform
import stat
import subprocess
import sys
import urllib.request
from pathlib import Path

VERSION = "1.2.7"
BASE = f"https://github.com/ccsb-scripps/AutoDock-Vina/releases/download/v{VERSION}"
ASSETS = {   # key: (asset file name, sha256)
    "win":       (f"vina_{VERSION}_win.exe",          "e0c4b2715e0c1a74f6e92d0f3be0328ac97542eafbc111e6b1efad897a73cce5"),
    "mac_arm64": (f"vina_{VERSION}_mac_aarch64",      "823c2bbacf26d72183861322345f0a89736aca66c8e81054c66f93af5ad623f1"),
    "mac_x64":   (f"vina_{VERSION}_mac_x86_64",       "9f44ccbb163223613283a75d0be53235d9e63f4da08292cb7196144f9838b7f9"),
    "linux":     (f"vina_{VERSION}_linux_x86_64",     "f31f774f723bba7bbe6e9d1c47577020eea9a8da16424284c043d22593570644"),
}
BIN = Path(__file__).resolve().parents[1] / "bin"


def platform_key() -> str:
    machine = platform.machine().lower()
    if sys.platform == "win32":
        return "win"
    if sys.platform == "darwin":
        return "mac_arm64" if machine in ("arm64", "aarch64") else "mac_x64"
    return "linux"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()
    key = platform_key()
    name, expected = ASSETS[key]
    target = BIN / ("vina.exe" if key == "win" else "vina")
    BIN.mkdir(exist_ok=True)
    if target.exists() and not args.force and sha256(target) == expected:
        print(f"Vina {VERSION} already present: {target}")
        return 0
    url = f"{BASE}/{name}"
    print(f"Downloading {url}")
    tmp = target.with_suffix(".download")
    with urllib.request.urlopen(url, timeout=120) as resp, open(tmp, "wb") as out:
        out.write(resp.read())
    got = sha256(tmp)
    if got != expected:
        tmp.unlink(missing_ok=True)
        print(f"CHECKSUM MISMATCH for {name}\n expected {expected}\n got      {got}", file=sys.stderr)
        return 1
    tmp.replace(target)
    target.chmod(target.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    if sys.platform == "darwin":                       # Apple Silicon refuses unsigned code: ad-hoc sign
        subprocess.run(["codesign", "--force", "--sign", "-", str(target)], check=False)
        subprocess.run(["xattr", "-d", "com.apple.quarantine", str(target)], check=False,
                       stderr=subprocess.DEVNULL)
    print(f"Verified and installed: {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
