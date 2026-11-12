"""Write server/roster.json from the app's roster, so the server and the app always agree on names, RCh. and roles.

    python scripts/export_roster.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from qrksdock.core import rules          # noqa: E402

roster = [{"initials": p["initials"], "display_name": p["display_name"], "role": p["role"]} for p in rules.roster()]
(ROOT / "server" / "roster.json").write_text(json.dumps(roster, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
print("wrote server/roster.json:", ", ".join(p["display_name"] for p in roster))
