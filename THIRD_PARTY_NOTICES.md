# Third-party notices

QRKSDock bundles or depends on the open-source software below. License names are read from each package's own metadata.

| Component | Version | License | Home page |
| --- | --- | --- | --- |
| AutoDock Vina (bundled executable) | 1.2.7 | Apache-2.0 | https://github.com/ccsb-scripps/AutoDock-Vina |
| Montserrat font (bundled) | 7.x | SIL Open Font License 1.1 | assets/fonts/LICENSE-Montserrat.txt |
| PySide6-Essentials | 6.12.0 | LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only | https://pyside.org |
| rdkit | 2026.9.1 | BSD-3-Clause | https://github.com/kuelumbus/rdkit-pypi |
| meeko | 0.8.0 | GNU Lesser General Public License v2 or later (LGPLv2+) | https://github.com/forlilab/meeko |
| molscrub | 0.3.2 | GPL-v3 | https://github.com/forlilab/molscrub |
| pdb2pqr | 3.8.0 | BSD License | https://www.poissonboltzmann.org |
| propka | 3.5.1 | GNU Lesser General Public License v2 (LGPLv2) | http://propka.org |
| reportlab | 4.4.10 | BSD License | https://www.reportlab.com/ |
| numpy | 2.4.4 | BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0 | https://numpy.org |
| pillow | 12.1.1 | MIT-CMU | https://github.com/python-pillow/Pillow/releases |

## Licensing flag: the Scrubber is GPL-3.0
`molscrub` (the Scrubber used for protonation and 3D generation) declares the GNU GPL v3. Using QRKSDock inside QRKS Scientific is unaffected.
If QRKSDock is ever given, sold or licensed to anyone outside the company, the GPL terms for the combined program must be reviewed by a lawyer,
or the Scrubber step replaced. It is used in exactly one module (`src/qrksdock/core/ligands.py`) so it can be swapped without touching the rest of the app.

PySide6 (Qt for Python) is distributed under the LGPL. QRKSDock ships it as separate, replaceable libraries inside the app folder.
If QRKSDock is ever distributed outside QRKS Scientific, have the license obligations of each component reviewed.
