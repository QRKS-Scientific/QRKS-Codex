"""Create or reset the temporary passwords for the six lead accounts.

    python scripts/make_accounts.py              # new temporary passwords for all six leads
    python scripts/make_accounts.py --reset JER  # new temporary password for one lead only

What it writes
  * src/qrksdock/data/accounts.json   salted hashes only (safe to commit to a PRIVATE repository)
  * FIRST_LOGIN_PASSWORDS.txt         the readable temporary passwords, in the folder you run this from

Hand each lead their own line through a private channel, then delete FIRST_LOGIN_PASSWORDS.txt.
NEVER commit that file (it is git-ignored). Each lead must choose their own password at first sign-in.
After changing accounts.json, rebuild the app (push a new tag) so the installers carry the new hashes.
"""
from __future__ import annotations

import argparse
import json
import secrets
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from qrksdock.core import accounts, rules                      # noqa: E402

ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"                  # no 0/O, 1/I: easy to read aloud


def temp_password() -> str:
    raw = "".join(secrets.choice(ALPHABET) for _ in range(12))
    return "-".join(raw[i:i + 4] for i in range(0, 12, 4))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reset", metavar="INITIALS", help="reset one account only, e.g. JER")
    args = ap.parse_args()
    target = ROOT / "src" / "qrksdock" / "data" / "accounts.json"
    current = json.loads(target.read_text(encoding="utf-8")) if target.exists() else {"accounts": {}}
    roster = {p["initials"]: p for p in rules.roster()}
    who = [args.reset.upper()] if args.reset else list(roster)
    unknown = [w for w in who if w not in roster]
    if unknown:
        print("Unknown initials:", ", ".join(unknown), "| valid:", ", ".join(roster), file=sys.stderr)
        return 1
    lines = []
    for ini in who:
        pw = temp_password()
        current["accounts"][ini] = accounts.hash_password(pw)
        lines.append(f"{ini:<4} {roster[ini]['display_name']:<26} {roster[ini]['role']:<22} {pw}")
    current["version"] = 1
    current["kdf"] = "pbkdf2_sha256"
    target.write_text(json.dumps(current, indent=2) + "\n", encoding="utf-8")
    out = Path("FIRST_LOGIN_PASSWORDS.txt")
    out.write_text("QRKSDock temporary passwords. Give each lead their own line privately, then DELETE this file.\n"
                   "Each lead chooses a new password at first sign-in.\n\n" + "\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote hashes to {target}\nWrote readable temporary passwords to {out.resolve()}\n")
    print("\n".join(lines))
    print("\nNow: rebuild the app so installers carry the new hashes, hand out the passwords privately, delete the .txt file.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
