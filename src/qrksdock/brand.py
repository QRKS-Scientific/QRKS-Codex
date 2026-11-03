"""QRKS Scientific brand tokens. Change colours here and the whole app follows.

The colours below are sampled from the supplied logo artwork so the interface matches
the logos exactly. PORTFOLIO_PALETTE holds the hex codes written in the business
portfolio, which differ slightly from the artwork; swap `ACTIVE` if the portfolio
codes should win.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Palette:
    blue: str        # primary: wordmarks, primary buttons
    blue_deep: str   # gradient end, pressed states
    sky: str         # gradient start, highlights, links
    yellow: str      # focal data callouts, tier highlights
    ink: str         # body text
    muted: str       # secondary text
    canvas: str      # window background
    surface: str     # panels
    border: str
    ok: str
    warn: str
    danger: str


LOGO_PALETTE = Palette(
    blue="#035DE0", blue_deep="#015ADF", sky="#02C6FF", yellow="#F4C327",
    ink="#10203F", muted="#5A6A85", canvas="#F4F7FC", surface="#FFFFFF",
    border="#D6DEEB", ok="#0B8A5B", warn="#B7791F", danger="#C0392B",
)

PORTFOLIO_PALETTE = Palette(
    blue="#001CDE", blue_deep="#001CDE", sky="#0083FA", yellow="#D89101",
    ink="#10203F", muted="#5A6A85", canvas="#F4F7FC", surface="#FFFFFF",
    border="#D6DEEB", ok="#0B8A5B", warn="#B7791F", danger="#C0392B",
)

ACTIVE = LOGO_PALETTE
FONT_FAMILY = "Montserrat"
TAGLINE = "transform. collaborate. create."
