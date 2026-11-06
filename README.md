# QRKSDock Desktop

The QRKS Scientific protein-ligand docking workflow, as a desktop app for Windows and Apple Silicon Macs.
Runs entirely on the laptop: no server, no cloud. Client data stays in the run folders on Google Drive.

Pipeline: receptor PDB (cleaned in PyMOL) -> pdb2pqr/PROPKA protonation at pH 7.4 -> Meeko PDBQT ->
ligands via the Scrubber and Meeko -> **AutoDock Vina 1.2.7** -> redocking validation -> results table, run manifest, branded PDF report.

---

## For the leads: installing

Download the latest build from the repository's **Releases** page (or the shared Drive folder).

**Windows**: download `QRKSDock-windows-x64.zip`, right-click > *Extract All*, open the `QRKSDock` folder and double-click `QRKSDock.exe`.
Windows SmartScreen may say "Windows protected your PC" because the app is not code-signed. Click *More info* > *Run anyway*.

**Mac (Apple Silicon, macOS 14 or later)**: open `QRKSDock-macos-arm64.dmg`, drag **QRKSDock** into *Applications*.
The first time, **right-click the app > Open > Open**. If macOS still refuses, run this once in Terminal:
`xattr -dr com.apple.quarantine /Applications/QRKSDock.app`

**First run:** choose *Help > System check*. Every line should say OK. If any says FAIL, copy the text and send it to the Technical Lead.

### Using it

1. **Project**: choose the runs folder (ideally inside Google Drive), type the client code (for example `QC-001`), optionally pick a package, and click **Create run**.
   The app issues the next QDOCK code (`QDOCK-260824-001`). To continue earlier work, double-click a run in the table, or use **Open run folder…**.
   Pick who you are in the top-right box; it is recorded in the activity log and the manifest. Nothing is blocked.
2. **Receptor**: choose the PDB you cleaned in PyMOL. Optionally add the co-crystal ligand as `.sdf` (export from PyMOL) for validation and a focused box. Click *Prepare receptor and box*.
3. **Ligands**: paste `SMILES name` lines (and peptide sequences, 2-6 residues). *Check ligands*, then *Prepare ligands*.
4. **Docking**: *Run validation* first (redocks the reference ligand; the top pose should be within 2.0 Å of the crystal pose), then *Run docking*. Vina chooses its own random seed and the app records it.
5. **Results**: ranked table (double-click a ligand name to rename it), the top 10 poses of the selected ligand, estimated pKd, CSV export, the raw Vina log (`vina_output.log`), and the PDF report.
   Choose **Draft (watermarked)** or **Final (no watermark)** before generating the report.

Everything is saved inside the run folder: `input/`, `work/`, `results/`, `reports/`, `logs/`. Closing the app and reopening the run picks up where you left off.

### Things to know

* **Cofactors, ions and waters are removed** from the receptor. If a ligand binds next to a cofactor (NADP, heme, a metal), redocking validation will usually fail. That is the validation doing its job, not a bug.
* Redocking validation was checked on Abl kinase + imatinib (PDB 1IEP): 0.21 Å. It correctly flags 3α-HSD + testosterone (1AFS) when NADP is removed.
* Peptides of 5-6 residues are very flexible; Vina poses are less reliable. The report says so.
* Contact residues and polar contacts are simple distance lists, not a validated interaction profile. Use PyMOL for 3D interaction mapping.
* Protein-protein docking and ADMETox are not part of this app.

---

## For developers

```bash
python -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\Activate.ps1
pip install -r requirements.txt pytest pypdf pyinstaller==6.22.3
python scripts/fetch_vina.py         # downloads Vina 1.2.7, verifies its SHA-256
python -m qrksdock doctor            # check every component
python -m qrksdock                   # open the app
python -m pytest -q                  # fast tests;  QRKS_SLOW=1 adds the imatinib benchmark
python -m qrksdock selftest          # tiny end-to-end docking job (also run inside each built app by CI)
```

Layout: `src/qrksdock/core` is the engine (no GUI imports); `src/qrksdock/gui` is a thin PySide6 layer on top.

| Change this | Edit |
| --- | --- |
| Tier limits, roster, who may do what, docking defaults | `src/qrksdock/data/rules.json` |
| Colours | `src/qrksdock/brand.py` (logo-sampled palette is active; the portfolio hex codes are kept beside it) |
| Logos / icons | drop originals in a folder and run `python scripts/make_assets.py --src <folder>` |
| Report wording and layout | `src/qrksdock/core/report.py` |
| Bundled Vina version | `scripts/fetch_vina.py` (update version and checksums) |

### Releasing

1. Bump the version in `src/qrksdock/__init__.py` only, and add an entry to `CHANGELOG.md`.
2. Commit, then `git tag v0.1.0 && git push --tags`.
3. GitHub Actions builds Windows and macOS (Apple Silicon) on GitHub's own machines, runs the tests, **runs a self-test inside each built app**, and publishes a Release.
   Use *Actions > Build QRKSDock > Run workflow* to build without tagging; the files appear under that run's *Artifacts*.

### Reproducibility

Every run writes `results/manifest.json`: software versions, all parameters, the random seed, and SHA-256 hashes of inputs and outputs.
Its hash is the **Run ID** printed in the report. Vina chooses its own random seed and prints it in its log; QRKSDock records that seed per ligand,
so the same inputs, Vina version, CPU thread count and recorded seed give identical scores.

Keep this repository **private**, and never commit client data or lead photos (run folders such as `QC-*/` are git-ignored).
