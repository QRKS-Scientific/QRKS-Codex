"""Docking search box (blind, around a reference ligand, or manual) and exhaustiveness advice."""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import TypeAlias

import numpy as np

from qrksdock.core import rules

Vector3: TypeAlias = tuple[float, float, float]


def _vector3(values: Iterable[float]) -> Vector3:
    coords = tuple(float(value) for value in values)
    if len(coords) != 3:
        raise ValueError("A box vector must contain exactly three coordinates.")
    return coords[0], coords[1], coords[2]


@dataclass
class Box:
    center: tuple[float, float, float]
    size: tuple[float, float, float]
    mode: str = "manual"            # blind | reference | manual

    @property
    def volume(self) -> float:
        return float(np.prod(self.size))

    def to_dict(self) -> dict:
        d = asdict(self)
        d["volume_A3"] = round(self.volume, 1)
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Box":
        return cls(tuple(d["center"]), tuple(d["size"]), d.get("mode", "manual"))

    def summary(self) -> str:
        c, s = self.center, self.size
        return (f"{self.mode} box: centre ({c[0]:.1f}, {c[1]:.1f}, {c[2]:.1f}), "
                f"size {s[0]:.1f} x {s[1]:.1f} x {s[2]:.1f} Å")


def read_pdb_xyz(path: Path, heavy_only: bool = True) -> np.ndarray:
    pts = []
    for line in Path(path).read_text(errors="replace").splitlines():
        if not line.startswith(("ATOM", "HETATM")):
            continue
        element = line[76:78].strip() or line[12:16].strip().lstrip("0123456789")[:1]
        if heavy_only and element.upper() == "H":
            continue
        pts.append((float(line[30:38]), float(line[38:46]), float(line[46:54])))
    if not pts:
        raise ValueError(f"No atoms found in {path}")
    return np.array(pts)


def box_blind(receptor_pdb: Path) -> Box:
    xyz = read_pdb_xyz(receptor_pdb)
    pad = rules.docking_defaults()["box_padding_blind"]
    lo, hi = xyz.min(axis=0), xyz.max(axis=0)
    center = _vector3((lo + hi) / 2)
    size = _vector3(hi - lo + 2 * pad)
    return Box(center, size, "blind")


def box_from_reference(centroid: Iterable[float], extent: Iterable[float]) -> Box:
    cfg = rules.docking_defaults()
    size = _vector3(max(float(e) + 2 * cfg["box_padding_ligand"], cfg["box_min_size"]) for e in extent)
    return Box(_vector3(centroid), size, "reference")


def box_manual(center: Iterable[float], size: Iterable[float]) -> Box:
    center_vector, size_vector = _vector3(center), _vector3(size)
    if any(side <= 0 for side in size_vector):
        raise ValueError("Box sizes must be positive.")
    return Box(center_vector, size_vector, "manual")


def recommended_exhaustiveness(box: Box) -> int:
    """Vina's default (8) is meant for small boxes. Larger search volumes need more sampling."""
    v = box.volume
    if v <= 30 ** 3:
        return 16
    if v <= 50 ** 3:
        return 24
    return 32


def box_warnings(box: Box) -> list[str]:
    out = []
    if max(box.size) > 70:
        out.append("Large search box (over 70 Å): runs are slow and pose accuracy drops. "
                   "Use blind docking to find the pocket, then re-dock with a focused box.")
    if min(box.size) < 15:
        out.append("A box side under 15 Å may be too small for the ligand to move.")
    return out
