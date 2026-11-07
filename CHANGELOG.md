# Changelog

All notable changes to QRKSDock are recorded here. Format: [Keep a Changelog](https://keepachangelog.com), versions follow [Semantic Versioning](https://semver.org).

- **MAJOR** (X.0.0): a change that breaks saved data or removes a feature leads rely on.
- **MINOR** (0.X.0): a new feature or a visible behaviour change.
- **PATCH** (0.0.X): a bug fix with no change in behaviour.

Versions stay below 1.0.0 until the first paid client delivery has been produced and checked on both Windows and Mac.
The version number is written only in `src/qrksdock/__init__.py`.

## [0.4.0] - 2026-11-07

### Added
- **Login screen.** The app starts on a sign-in screen showing the six lead accounts. There is no registration. Each lead signs in with a temporary password, then must choose their own at first sign-in on that laptop. Repeated wrong passwords lock the account for 30 s, then 60 s, 120 s and so on. A **Sign out** button in the header returns to the login screen.
- Profile area in the header (photo or initials, name, role) replaces the "Signed in as" dropdown. The signed-in lead is recorded in the activity log and the manifest.
- `scripts/make_accounts.py` creates or resets the temporary passwords. Only salted PBKDF2 hashes are stored in the app; the readable passwords go to a separate file that is never committed.
- Optional profile photos: put `LEM.png` (and so on) in the `avatars` folder of the settings folder. Photos are never stored in the repository or installer.
- Vina log verbosity 2: `vina_output.log` now includes the full energy breakdown of every pose (intermolecular, internal, torsional and unbound energies). The setting is recorded in the manifest.
- Every input on the Receptor and Docking pages has a title and a wrapping guide, so no placeholder or explanation is cut off.
- The self-test now also builds the login screen, which proves the bundled accounts file and fonts load in each installer.

### Changed
- **Typeface.** Montserrat is removed from the interface. On Mac the app uses the system font, which is SF Pro. On other systems it uses the bundled open font Inter (with Inter Display for titles). SF Pro cannot be embedded under Apple's licence. `FONT_MODE` in `brand.py` switches between the system font and Inter everywhere. Montserrat remains only inside PDF reports until the Canva template arrives.
- Receptor and Docking pages use two columns; the right column shows the preparation summary and the run output. Inputs are taller and the window opens larger.
- The sign-in lead is the operator for every run; roles do not restrict anything.

### Notes
- The accounts file in this release holds placeholder temporary passwords. Run `python scripts/make_accounts.py` before distributing, and rebuild.
- A login is a gate against casual use. Client data is protected by Google Drive permissions and disk encryption.
- Next: v0.5.0 report changes (Canva layout, peptide section rule, PyMOL images).

## [0.3.0] - 2026-11-05

### Added
- Client codes (`QC-001`) and QDOCK codes (`QDOCK-260824-001`, serial unique per day across all clients). A run lives in `<runs folder>/QC-001/QDOCK-260824-001/` with `input/`, `work/`, `results/`, `reports/` and `logs/`.
- **Project** page: create a run, open a run, and see every run in the runs folder with its stage, ligand count and best affinity. Double-click a run to open it.
- A folder made by hand (a `QDOCK-...` folder inside a `QC-...` folder) is adopted when opened.
- Optional package (Hadron, Fermion, Boson): limits are checked only when a package is chosen.
- Report type choice on the Results page: **Draft** (diagonal watermark, the default) or **Final** (no watermark).
- `logs/activity.jsonl`: a plain record of who did what and when.

### Changed
- Any lead can run any step. The operator is recorded in the activity log and the manifest; nothing is blocked.
- Manifest records `qdock_code`, `client_code` and `package` instead of ticket fields.
- Report: header shows client and QDOCK codes; file names are `<QDOCK code>_Technical_Report_DRAFT.pdf` or `_FINAL.pdf`.
- Folder names no longer use square brackets.

### Removed (breaking)
- The ticket system: `ticket.json`, status flags (activated and paid, QA passed, balance cleared, report signed), the payment gate, role permissions, per-event files, and test tickets.
- The Integrity Seal and the sign-off block in the report (pulled forward from the report phase because they depended on the ticket flags).

### Migration
- Folders created by 0.1.0 or 0.2.0 (ticket folders) cannot be opened by 0.3.0. No production data existed, so no converter is provided.
- Next: v0.4.0 adds the login screen and the UI redesign.

## [0.2.0] - 2026-11-04

### Added
- Top 10 poses per ligand, ranked by affinity, shown in a pose table under the results and in the CSV and report.
- `vina_output.log`: Vina's complete, unmodified console output for every ligand, saved in `results/` (mandatory client deliverable). Per-ligand logs are kept in `work/docking/logs/`.
- Estimated pKd next to every affinity (pKd = -dG / (2.303 R T) at 298.15 K), with a caution that it is a rough conversion.
- Double-click a ligand name in the results table to rename it. Exports, pose files and the report use the new name; the Run ID does not change.
- `poses.csv` (one row per pose) alongside `results.csv`.

### Changed
- Poses per ligand now defaults to 10 and the energy range to 10 kcal/mol, so Vina does not cut the list short.
- Vina now chooses its own random seed. The seed is read from Vina's log and stored in the manifest, so a run can still be reproduced.
- The ligand preparation seed (RDKit 3D generation) moved to `ligand_prep_seed` in `rules.json`.
- Report: estimated pKd column and caution, pose strip per ligand, seed wording in Methods.
- The version number now lives in one place only.
- Window opens sized to the laptop's screen; each page scrolls instead of clipping, and table selection is easier to read.

### Removed
- The Random Seed input in the Docking panel.

### Notes
- Pose count is "up to 10". Very tight sites can return fewer; the report states how many were returned.
- Next: v0.3.0 removes the ticket system in favour of QDOCK and client codes.

## [0.1.0] - 2026-11-03

### Added
- First build: ticket folders, role-based gates, receptor and ligand preparation (pdb2pqr/PROPKA, Meeko, Scrubber), AutoDock Vina docking, redocking validation, run manifest, branded PDF report, Windows and Mac packaging.
