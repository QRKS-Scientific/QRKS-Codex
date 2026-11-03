"""Command line entry point:  qrksdock [gui | doctor | selftest [--out FILE] | version]"""
from __future__ import annotations

import argparse
import json
import sys


def main(argv: list[str] | None = None) -> int:
    import os
    for name in ("stdout", "stderr"):                   # windowed Windows apps start with no console streams
        if getattr(sys, name) is None:
            setattr(sys, name, open(os.devnull, "w", encoding="utf-8"))
    ap = argparse.ArgumentParser(prog="qrksdock", description="QRKSDock Desktop")
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("gui", help="open the application (default)")
    sub.add_parser("doctor", help="check that every component works on this computer")
    st = sub.add_parser("selftest", help="run a tiny end-to-end docking job and report pass/fail")
    st.add_argument("--out", help="write the JSON result to this file")
    sub.add_parser("version")
    args, _ignored = ap.parse_known_args(argv)        # macOS may pass launcher flags such as -psn_...

    if args.cmd == "version":
        from qrksdock import __version__
        print(__version__)
        return 0
    if args.cmd == "doctor":
        from qrksdock.core import diagnostics
        items = diagnostics.system_check()
        print(diagnostics.format_check(items))
        return 0 if all(i["ok"] for i in items) else 1
    if args.cmd == "selftest":
        from qrksdock.core import diagnostics
        result = diagnostics.selftest(log=lambda s: print(s, flush=True))
        text = json.dumps(result, indent=2)
        print(text)
        if args.out:
            with open(args.out, "w", encoding="utf-8") as f:
                f.write(text)
        return 0 if result["ok"] else 1
    from qrksdock.gui.app import run_gui
    return run_gui()


if __name__ == "__main__":
    sys.exit(main())
