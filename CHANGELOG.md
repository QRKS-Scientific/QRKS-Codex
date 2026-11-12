# Changelog

All notable changes to QRKSDock are recorded here. Format: [Keep a Changelog](https://keepachangelog.com), versions follow [Semantic Versioning](https://semver.org).

- **MAJOR** (X.0.0): a change that breaks saved data or removes a feature leads rely on.
- **MINOR** (0.X.0): a new feature or a visible behaviour change.
- **PATCH** (0.0.X): a bug fix with no change in behaviour.

Versions stay below 1.0.0 until the first paid client delivery has been produced and checked on both Windows and Mac.
The version number is written only in `src/qrksdock/__init__.py`.

## [0.5.0] - 2026-11-08

### Added
- **QRKSDock server** (`server/`): a small FastAPI service for sign-in, run codes and activity logs. All docking computation stays on the laptops. Includes Docker, HTTPS proxy (Caddy), backup and dynamic-DNS scripts, an admin command-line tool, and a runbook (`server/README.md`).
- **Central sign-in.** Passwords live only on the server (Argon2id). A temporary password works once and expires after 7 days; after the first change it is dead on every laptop. Sessions use 15-minute access tokens and rotating refresh tokens; a replayed token ends the whole session. Lockout is per account and per IP, at most 3 laptops per lead, and a password change signs out every other laptop.
- **7-day offline grace.** The app resumes your saved sign-in on startup, and keeps working with no internet for up to 7 days after the server last confirmed it. The refresh token is kept in the operating system keychain (macOS Keychain, Windows Credential Manager), never in a file.
- **Server-issued QDOCK codes**, so two laptops can never create the same code. Creating a new run needs a connection; existing runs work offline.
- **Activity sync.** Events queue in a local outbox and upload when online (idempotent, retried safely). Only allowed fields are ever queued or accepted: no ligand names, SMILES, sequences, structures or scores leave the laptop. The header shows Online or Offline with the number of events waiting.
- A run folder created by hand is registered with the server automatically on its first upload.
- Self-test now checks the OS keychain (required on Windows and Mac) and the TLS certificate bundle in every installer.
- 66 new tests (29 for the laptop network layer, 9 end-to-end against the real server, 37 for the server).

### Changed
- If `src/qrksdock/data/server.json` has a server address (or `QRKS_SERVER_URL` is set), the app uses the server and has **no local temporary-password path**. With no address it behaves as in 0.4.x with local accounts (development).
- `Run.log()` hands each event to an optional sink; the core engine still contains no network code.
- New dependencies: `httpx`, `keyring`.

### Notes
- Windows and Mac keychain behaviour is checked by the installers' self-test in GitHub Actions, not here.
- "Free" hosting has catches: see `server/README.md`. The server runs on any Ubuntu VM.
- The accounts file from 0.4.0 is unused whenever a server is configured. Set up accounts on the server with `python -m app.admin init`.
- Next: v0.6.0 report changes (Canva layout, peptide section rule, PyMOL images).

## [0.4.1] - 2026-11-07

### Changed
- All six leads are Registered Chemists and now show **RCh.** everywhere a name appears: login tiles, the header, the status line, the password prompt and the report's "Prepared by". The title is stored as data (`credential` in `rules.json`) and one function (`rules.display_name`) builds every display name, so it cannot drift between screens.
- Build workflow runs on `windows-latest` and `macos-latest` (Apple Silicon). GitHub retired the macOS 14 runner images on 2 November 2026, so the old label would have stopped working. Packaging still uses `packaging/qrksdock.spec`.

### Added
- `docs/adr/0001-central-auth-and-sync-server.md`: the design for a private sign-in and sync server with all computation kept on each laptop (proposed, not yet built).
- Tests that lock in the RCh. display and the workflow's runner labels and spec path, so a later build cannot undo them.

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
