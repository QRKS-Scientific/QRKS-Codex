"""Convert a Vina score (kcal/mol) to an estimated dissociation constant.

    dG = R T ln(Kd)   =>   pKd = -log10(Kd) = -dG / (ln(10) R T)

At 298.15 K, ln(10) R T = 1.3646 kcal/mol, so a score of -9.0 kcal/mol gives pKd 6.6.
This is a rough conversion. Vina scores are approximations of binding free energy
(typical error is around 2 kcal/mol, i.e. about 1.5 pKd units), so the result is an
estimate for ranking, not a measured affinity.
"""
from __future__ import annotations

import math

R_KCAL_PER_MOL_K = 0.0019872041
DEFAULT_TEMP_K = 298.15


def estimate_pkd(dg_kcal_per_mol: float, temp_k: float = DEFAULT_TEMP_K) -> float:
    return -dg_kcal_per_mol / (math.log(10) * R_KCAL_PER_MOL_K * temp_k) + 0.0   # + 0.0 avoids -0.0


def estimate_kd_molar(dg_kcal_per_mol: float, temp_k: float = DEFAULT_TEMP_K) -> float:
    return 10 ** (-estimate_pkd(dg_kcal_per_mol, temp_k))


def format_kd(kd_molar: float) -> str:
    if kd_molar >= 1:
        return "1 M or weaker"
    for unit, scale in (("mM", 1e-3), ("µM", 1e-6), ("nM", 1e-9), ("pM", 1e-12)):
        if kd_molar >= scale:
            return f"{kd_molar / scale:.3g} {unit}"
    return f"{kd_molar / 1e-12:.3g} pM"
