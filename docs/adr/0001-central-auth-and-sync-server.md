# ADR 0001: Central sign-in and sync server, local compute

Status: **Superseded by the Supabase Auth and Postgres integration in v0.5.1.** This ADR records the earlier custom FastAPI server proposal and implementation.
Decided by: QRKS Scientific technical lead. Date: 2026-11-07, decisions confirmed 2026-11-08.

## Decisions confirmed
- Build the server and remote sign-in **before** the report/Canva phase.
- **Offline grace: 7 days** from the last time the server confirmed the session.
- **Public HTTPS with rate limiting** on a free or low-cost host (no VPN). See `server/README.md` for what free really means.
- Run summaries are **derived from events** on the server, so there is no separate summary endpoint (fewer endpoints, no chemistry fields).
- All six leads are Registered Chemists; display names carry `RCh.` (see `rules.display_name`).

## Problem
v0.4.0 keeps accounts in a file inside each installation. Because every laptop is independent:
- a password changed on one laptop is unknown to the others;
- a temporary password can be used on any laptop that has the installer, and never expires;
- there is no single record of who ran what.

## Decision
A small private server (FastAPI) owns **sign-in, profiles, run registry and activity logs**.
**All computation stays on the laptop**: receptor preparation, ligand preparation, AutoDock Vina, pose extraction, PDF reports.

```
 laptop (Windows or Mac)                                  private server
 ┌───────────────────────────────┐   HTTPS + tokens    ┌────────────────────────────┐
 │ QRKSDock app                  │ ─────────────────▶  │ FastAPI                    │
 │  login · outbox · keychain    │ ◀─────────────────  │  auth · runs · events      │
 │  Vina · Meeko · PDF (LOCAL)   │                     │  SQLite/Postgres · backups │
 └──────────────┬────────────────┘                     └─────────────┬──────────────┘
                │ files (Drive for Desktop)                          │ service account (server only)
                ▼                                                    ▼
          Google Drive: input/ work/ results/ reports/        Google Sheets dashboard
```

### What lives where
| Data | Where | Why |
| --- | --- | --- |
| Password hashes, sessions, devices | server | one source of truth; revocation |
| Lead profiles (name, credential, role) | shipped in the app now; server later | credential display (`RCh.`) already in `rules.json` |
| QDOCK code allocation | server | removes same-day collisions between laptops |
| Run metadata and activity events | server (copied from the laptop outbox) | shared tracking and the Sheets dashboard |
| Receptors, ligands, poses, Vina logs, reports, manifests | laptop + Google Drive only | client IP; never sent through the API |
| Google API credentials | server only | never inside an installer |

**Data rule.** No ligand name, SMILES, sequence, structure or score leaves the laptop through the API. Allowed: codes, operator initials, timestamps, stage, counts, report generated, run ID (manifest hash).

## Sign-in and sessions
| Item | Design |
| --- | --- |
| Password storage | Argon2id, per-user salt, optional server-side pepper held in an environment secret |
| Temporary password | one-time, expires after 7 days, forces a change; once changed it is dead everywhere |
| Access token | signed JWT, 15 minutes; claims `sub`, `role`, `did` (device), `jti`, `iss`, `aud`, `scope` |
| Refresh token | random 256-bit opaque value; only its SHA-256 is stored; 14 days idle, 30 days absolute; **rotates on every use**; reuse of an old one revokes the whole session family |
| Limited scope | after a temporary-password sign-in the token carries `scope=pwd_change` and can do nothing but change the password |
| Storage on the laptop | OS keychain (`keyring`: macOS Keychain, Windows Credential Manager). Access token in memory only. Never in `QSettings` or a file |
| Devices | each install registers a device ID; at most 3 active devices per lead; revocable |
| Lockout | per account (30 s, doubling, capped at 15 min) and per IP; identical error messages; constant-time compare |
| Sign out / password change | sign out revokes that refresh token; a password change revokes all other sessions |
| Admin | v1: a server-side command (`python -m app.admin reset JER`). No admin endpoints exposed |
| Transport | HTTPS only; the app refuses `http://` except `localhost` in development |

## API (v1)
```
POST /v1/auth/login           {initials, password, device_id, device_name} -> tokens, must_change
POST /v1/auth/refresh         {refresh_token} -> new tokens (rotation)
POST /v1/auth/logout          revoke this session
POST /v1/auth/change-password {current, new}
GET  /v1/me                   initials, display_name, role
POST /v1/runs                 {client_code[, code, request_id]} -> allocates QDOCK-YYMMDD-NNN (Manila date), or registers an existing code
GET  /v1/runs?client=QC-001   dashboard rows derived from events (stage, ligand count, reports)
GET  /v1/runs/{code}/events
POST /v1/runs/{code}/events   batch of activity events, idempotent by event id
GET  /v1/meta                 {api: 1, min_app: "0.6.0"}   (app warns if too old)
GET  /healthz
```

## Laptop-side changes
- `AuthProvider` interface with `LocalAuthProvider` (today's behaviour, development and tests) and `RemoteAuthProvider`. The login screen depends only on the interface.
- `net/` package: HTTP client (timeouts, retries), session store (keychain), **outbox** (a local queue of events with UUIDs, replayed when online).
- `Run.log()` stays the single place events are written. It appends to `logs/activity.jsonl` and enqueues the same event in the outbox. A server outage never blocks a docking job.
- In server mode there is **no local temporary-password path**. Offline use relies only on the cached refresh token (see Offline).

## Offline behaviour (decision needed)
Docking and reports never need the network. Sign-in does. Policy options: strict online sign-in, or silent resume from the cached refresh token for up to N days (recommended N = 7) while events queue in the outbox.

## Server layout
```
qrksdock-server/
  app/ main.py config.py db.py models.py schemas.py security.py deps.py admin.py
       routers/ auth.py runs.py events.py
       services/ sheets.py
  alembic/  tests/  Dockerfile  docker-compose.yml  Caddyfile  RUNBOOK.md
```
Settings come from environment variables (`pydantic-settings`); secrets are never in the repository. SQLite in WAL mode with continuous backup is enough for six leads; move to Postgres if the team grows.

## Deployment
- Small VPS (1 vCPU, 1-2 GB RAM), Ubuntu LTS, automatic security updates, firewall allowing only what is needed.
- Docker Compose: FastAPI behind Caddy (automatic TLS).
- **Network exposure (decision needed):** public HTTPS with rate limiting, or private-network only (for example Tailscale), which removes the public attack surface at the cost of installing a small client on each laptop.
- Backups tested by an actual restore; uptime check; auth events (success, failure, IP, device) logged without passwords.

## Alternatives considered
1. Keep local accounts (status quo): simplest, cannot fix the three problems above.
2. Hosted identity provider (Auth0, Supabase Auth, Firebase) or Google Workspace sign-in: the QRKS server then stores no passwords, which removes the biggest liability, and MFA comes free. The trade-off is a dependency and per-user setup. The `AuthProvider` interface keeps this option open.
3. Custom FastAPI auth (this ADR): full control and exactly the pre-made-account flow wanted, but QRKS becomes responsible for password storage, patching and breach response.

## Consequences
- A server to run, patch and back up. Sign-in needs connectivity (mitigated by the offline grace period).
- Changes the old plan for Google sync: the **server** writes the Sheets dashboard with a service account, so Google credentials never ship to laptops. Drive for Desktop still syncs the run folders.
- Run registry removes QDOCK code collisions, which local folder scanning cannot prevent between offline laptops.

## Build plan
1. Introduce `AuthProvider` with `LocalAuthProvider`; no behaviour change; tests stay green.
2. Server repo with tests for: login, lockout, one-time temporary password, refresh rotation and reuse detection, device limit.
3. Client net layer: `RemoteAuthProvider`, keychain session, outbox, offline grace; tested against the server in-process and against a mocked transport.
4. Run registry and events (server-issued QDOCK codes, idempotent event upload).
5. Sheets dashboard worker on the server.
6. Runbook, restore drill, and a short security review before real client data is involved.

## Implementation status
| Step | Status |
| --- | --- |
| 1. `AuthProvider` seam (`AccountStore` and `RemoteAuthProvider`) | done, v0.5.0 |
| 2. Server with tests (37) | done |
| 3. Client network layer: keychain session, outbox, 7-day offline grace (+ 29 tests) | done |
| 4. Run registry and idempotent events, server-issued codes | done |
| 5. Google Sheets dashboard worker on the server | not started |
| 6. Runbook, restore drill, security review | runbook written (`server/README.md`); the drill and review are yours to do before real client data |

Not verified yet: the Windows Credential Manager and macOS Keychain paths (the installers' self-test checks them in CI), and any real internet deployment.
