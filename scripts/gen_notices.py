"""Write THIRD_PARTY_NOTICES.md from the license metadata of the installed packages."""
from __future__ import annotations

from importlib.metadata import PackageNotFoundError, metadata, version
from pathlib import Path

PACKAGES = [("AutoDock Vina (bundled executable)", None), ("PySide6-Essentials", "PySide6-Essentials"), ("rdkit", "rdkit"),
            ("meeko", "meeko"), ("molscrub", "molscrub"), ("pdb2pqr", "pdb2pqr"), ("propka", "propka"),
            ("reportlab", "reportlab"), ("numpy", "numpy"), ("pillow", "pillow")]
OUT = Path(__file__).resolve().parents[1] / "THIRD_PARTY_NOTICES.md"


def lic(m) -> str:
    expr = m.get("License-Expression")
    if expr:
        return expr
    classifiers = [c.split("::")[-1].strip() for c in (m.get_all("Classifier") or []) if c.startswith("License ::")]
    if classifiers:
        return "; ".join(classifiers)
    text = (m.get("License") or "").strip().splitlines()
    return text[0][:90] if text else "see package"


def main() -> None:
    lines = ["# Third-party notices", "",
             "QRKSDock bundles or depends on the open-source software below. License names are read from each package's own metadata.",
             "", "| Component | Version | License | Home page |", "| --- | --- | --- | --- |",
             "| AutoDock Vina (bundled executable) | 1.2.7 | Apache-2.0 | https://github.com/ccsb-scripps/AutoDock-Vina |",
             "| Montserrat font (bundled) | 7.x | SIL Open Font License 1.1 | assets/fonts/LICENSE-Montserrat.txt |"]
    for label, dist in PACKAGES[1:]:
        try:
            m = metadata(dist)
            home = m.get("Home-page") or next((u.split(",")[-1].strip() for u in (m.get_all("Project-URL") or [])), "")
            lines.append(f"| {label} | {version(dist)} | {lic(m)} | {home} |")
        except PackageNotFoundError:
            lines.append(f"| {label} | not installed | | |")
    lines += ["", "## Licensing flag: the Scrubber is GPL-3.0",
              "`molscrub` (the Scrubber used for protonation and 3D generation) declares the GNU GPL v3. Using QRKSDock inside QRKS Scientific is unaffected.",
              "If QRKSDock is ever given, sold or licensed to anyone outside the company, the GPL terms for the combined program must be reviewed by a lawyer,",
              "or the Scrubber step replaced. It is used in exactly one module (`src/qrksdock/core/ligands.py`) so it can be swapped without touching the rest of the app.",
              "", "PySide6 (Qt for Python) is distributed under the LGPL. QRKSDock ships it as separate, replaceable libraries inside the app folder.",
              "If QRKSDock is ever distributed outside QRKS Scientific, have the license obligations of each component reviewed.", ""]
    OUT.write_text("\n".join(lines), encoding="utf-8")
    print("wrote", OUT)


if __name__ == "__main__":
    main()
