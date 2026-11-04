# Changelog

All notable changes to QRKSDock are recorded here. Format: [Keep a Changelog](https://keepachangelog.com), versions follow [Semantic Versioning](https://semver.org).

- **MAJOR** (X.0.0): a change that breaks saved data or removes a feature leads rely on.
- **MINOR** (0.X.0): a new feature or a visible behaviour change.
- **PATCH** (0.0.X): a bug fix with no change in behaviour.

Versions stay below 1.0.0 until the first paid client delivery has been produced and checked on both Windows and Mac.
The version number is written only in `src/qrksdock/__init__.py`.

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
