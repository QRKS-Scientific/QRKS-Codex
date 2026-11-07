"""Run the standalone AutoDock Vina executable.

The Vina Python bindings cannot be installed with pip on Windows or Apple Silicon, so
QRKSDock calls the official standalone executable instead. The same code path then works
on every laptop. The executable is bundled in bin/ (see scripts/fetch_vina.py); a user can
also point the app at their own copy.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from qrksdock import paths
from qrksdock.core.box import Box

ProgressCb = Callable[[float], None]
_VERSION_RE = re.compile(r"AutoDock Vina v?([\d.]+)")
_SEED_RE = re.compile(r"random seed:\s*(-?\d+)")
_RESULT_RE = re.compile(r"REMARK VINA RESULT:\s+(-?[\d.]+)\s+(-?[\d.]+)\s+(-?[\d.]+)")


class VinaError(Exception):
    pass


class VinaCancelled(Exception):
    pass


@dataclass
class Pose:
    mode: int
    affinity: float           # kcal/mol
    rmsd_lb: float
    rmsd_ub: float


@dataclass
class VinaRun:
    out_pdbqt: Path
    poses: list[Pose]
    seconds: float
    command: list[str] = field(default_factory=list)
    log_text: str = ""                 # Vina's complete, unmodified console output
    seed: int | None = None            # the seed Vina used (read from its log when chosen automatically)


def _no_window() -> int:
    return getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0


def candidate_paths(user_path: str | None = None) -> list[Path]:
    exe = "vina.exe" if sys.platform == "win32" else "vina"
    out: list[Path] = []
    if user_path:
        out.append(Path(user_path))
    if os.environ.get("QRKS_VINA"):
        out.append(Path(os.environ["QRKS_VINA"]))
    out.append(paths.bin_dir() / exe)
    for folder in os.environ.get("PATH", "").split(os.pathsep):
        if folder:
            out.append(Path(folder) / exe)
    return out


def find_vina(user_path: str | None = None) -> Path | None:
    for p in candidate_paths(user_path):
        if p.is_file():
            return p
    return None


def vina_version(exe: Path) -> str:
    try:
        res = subprocess.run([str(exe), "--version"], capture_output=True, text=True, timeout=30,
                             creationflags=_no_window())
    except (OSError, subprocess.SubprocessError) as exc:
        raise VinaError(f"Could not start Vina at {exe}: {exc}") from exc
    m = _VERSION_RE.search(res.stdout + res.stderr)
    if not m:
        raise VinaError(f"{exe} does not look like AutoDock Vina (output: {(res.stdout + res.stderr)[:120]!r})")
    return m.group(1)


def parse_seed(log_text: str) -> int | None:
    m = _SEED_RE.search(log_text)
    return int(m.group(1)) if m else None


def parse_poses(out_pdbqt: Path) -> list[Pose]:
    poses = []
    for line in Path(out_pdbqt).read_text(errors="replace").splitlines():
        m = _RESULT_RE.match(line)
        if m:
            poses.append(Pose(len(poses) + 1, float(m.group(1)), float(m.group(2)), float(m.group(3))))
    return poses


def default_cpus() -> int:
    return max(1, (os.cpu_count() or 2) - 1)           # leave one core so the window stays responsive


def run_vina(exe: Path, receptor: Path, ligand: Path, box: Box, out_pdbqt: Path, *,
             exhaustiveness: int, num_modes: int, energy_range: float, seed: int | None = None, cpu: int, verbosity: int = 2,
             progress: ProgressCb | None = None, cancel: threading.Event | None = None) -> VinaRun:
    import time

    cmd = [str(exe), "--receptor", str(receptor), "--ligand", str(ligand),
           "--center_x", f"{box.center[0]:.3f}", "--center_y", f"{box.center[1]:.3f}", "--center_z", f"{box.center[2]:.3f}",
           "--size_x", f"{box.size[0]:.3f}", "--size_y", f"{box.size[1]:.3f}", "--size_z", f"{box.size[2]:.3f}",
           "--exhaustiveness", str(exhaustiveness), "--num_modes", str(num_modes),
           "--energy_range", str(energy_range), "--cpu", str(cpu), "--verbosity", str(verbosity),
           "--out", str(out_pdbqt)]
    if seed is not None:
        cmd += ["--seed", str(seed)]
    t0 = time.time()
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            creationflags=_no_window())
    stars, raw = 0, bytearray()
    try:
        assert proc.stdout is not None
        while True:
            if cancel is not None and cancel.is_set():
                proc.terminate()
                proc.wait(timeout=10)
                raise VinaCancelled()
            ch = proc.stdout.read(1)
            if not ch:
                break
            raw += ch
            if ch == b"*" and progress is not None:
                stars += 1
                progress(min(stars / 51.0, 1.0))
        proc.wait()
    finally:
        if proc.poll() is None:
            proc.kill()
    text = raw.decode(errors="replace").replace("\r\n", "\n")
    if proc.returncode != 0 or not out_pdbqt.exists():
        raise VinaError(f"Vina failed (exit code {proc.returncode}). Last output:\n{text[-500:]}")
    poses = parse_poses(out_pdbqt)
    if not poses:
        raise VinaError("Vina finished but found no poses. Try a larger box or higher exhaustiveness.")
    return VinaRun(out_pdbqt, poses, time.time() - t0, cmd, text, parse_seed(text) if seed is None else seed)
