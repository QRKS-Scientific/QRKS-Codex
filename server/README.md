# QRKSDock server

A small private service for the six QRKS leads: **sign-in, run codes and activity logs**.
It never sees chemistry. Docking, receptor preparation and reports run on each laptop; client files travel through Google Drive only.
Design and reasons: `docs/adr/0001-central-auth-and-sync-server.md`.

## What it does
| Endpoint | Purpose |
| --- | --- |
| `POST /v1/auth/login`, `/refresh`, `/logout`, `/change-password` | sign-in, rotating sessions, password change |
| `GET /v1/me`, `/v1/meta`, `/healthz` | who am I, version handshake, health |
| `POST /v1/runs`, `GET /v1/runs` | issue the next `QDOCK-YYMMDD-NNN` (Manila date), register existing codes, dashboard rows |
| `POST /v1/runs/{code}/events` | upload activity events (idempotent; only allowed fields are kept) |

Security in one paragraph: Argon2id password hashes (optional pepper); a temporary password works once, expires in 7 days and is dead everywhere after the first change; 15-minute access tokens; refresh tokens rotate on every use and a replayed one ends the whole session; lockout 30 s doubling to 15 min; at most 3 laptops per lead; per-IP rate limits; no admin endpoints (everything administrative is a command on the server); the audit log never holds passwords.

## Develop and test
```bash
cd server
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
python -m pytest -q                       # 37 tests, a few seconds
```
Run locally: `QRKS_JWT_SECRET=$(openssl rand -hex 32) QRKS_DEBUG=true uvicorn app.main:app_from_env --factory --reload` (docs at `/docs` only when `QRKS_DEBUG=true`).

## Deploy (any Ubuntu 22.04/24.04 VM with a public IP)
1. **Name.** Point a hostname at the VM's public IP. A free DuckDNS name works (`deploy/update-duckdns.sh` keeps it current if the IP changes).
2. **Install Docker and sqlite3**: `sudo apt-get update && sudo apt-get install -y docker.io docker-compose-v2 sqlite3`.
3. **Copy this `server/` folder** to the VM, then:
   ```bash
   cp .env.example .env && nano .env        # set QRKS_DOMAIN, QRKS_JWT_SECRET (openssl rand -hex 32), optionally QRKS_PEPPER
   mkdir data && sudo chown 10001:10001 data
   sudo docker compose up -d --build        # Caddy fetches the HTTPS certificate automatically
   ```
4. **Create the six accounts** (temporary passwords are printed once; hand each lead theirs privately):
   ```bash
   sudo docker compose exec app python -m app.admin init --roster roster.json
   ```
5. **Check**: open `https://YOUR-HOSTNAME/healthz` (should show `{"ok":true}`).
6. **Point the app at it**: put `"url": "https://YOUR-HOSTNAME"` in `src/qrksdock/data/server.json`, tag a release, and the installers talk to the server. *Help > System check* shows the server line.
7. **Backups**: `sudo apt-get install -y sqlite3`, then cron `deploy/backup.sh` daily and copy the backups off the machine (see the script). **Do a restore drill once**: stop the app, copy a backup over `data/qrksdock.db`, start it, sign in.

## Everyday operations
```bash
sudo docker compose exec app python -m app.admin list                  # who exists, who still has a temporary password
sudo docker compose exec app python -m app.admin reset JER             # forgotten password: new temporary one, signed out everywhere
sudo docker compose exec app python -m app.admin devices JER           # which laptops are registered
sudo docker compose exec app python -m app.admin revoke-devices JER    # lost laptop: remove all of that lead's laptops
sudo docker compose exec app python -m app.admin disable JER           # someone leaves (also: enable)
sudo docker compose exec app python -m app.admin unlock JER
sudo docker compose exec app python -m app.admin audit --limit 50      # sign-in history (successes, failures, IPs)
```
Update the server: copy the new `server/` over, then `sudo docker compose up -d --build`.
Rotating `QRKS_JWT_SECRET` signs everyone out (they sign in again); do it if the secret may have leaked. Changing `QRKS_PEPPER` invalidates every password (use `reset` for all six).

## Where to host it: what "free" really means (checked November 2026)
| Option | Cost | Catches |
| --- | --- | --- |
| **Google Cloud e2-micro** (US regions only: us-west1, us-central1, us-east1) | VM and 30 GB disk free; **the external IPv4 address may cost about $0.005/hour (about $3.65 a month)**. Google's pricing page lists that charge; reports disagree on whether the free VM is exempt, so read your billing page | needs a card; 1 GB RAM; about 1 GB/month free outbound traffic (plenty here); set a $5 budget alert |
| **Oracle Cloud Always Free** | public IP included | free instances can be reclaimed after about a week of low use, which a login server always has; upgrading to Pay-As-You-Go avoids that and stays $0 within the free limits; capacity can be unavailable |
| **A small paid VPS** (about $4-6/month; Singapore is typically closest to the Philippines) | predictable | not free |
None of the free options has an uptime promise. The app is built for that: **7 days of offline sign-in**, and events queue until the server is back. Only creating a new run needs the server, because codes must stay unique.

## Security checklist before real client data is involved
- [ ] `.env` is not in the repository and is readable only by you (`chmod 600 .env`).
- [ ] HTTPS works and `http://` redirects (Caddy does this).
- [ ] The VM firewall allows only ports 22 (ideally your IP only), 80 and 443.
- [ ] SSH uses keys, password login is off, automatic security updates are on (`unattended-upgrades`).
- [ ] A backup was restored successfully at least once.
- [ ] Each lead changed their temporary password; `admin list` shows no one still on a temporary password.
- [ ] Philippine Data Privacy Act: the server stores six people's names and sign-in history. Have counsel confirm any registration or notice duties.

## Troubleshooting
- *The app says it cannot reach the server*: open `https://YOUR-HOSTNAME/healthz` in a browser. If that fails, check the VM is running and the DNS name points at its current IP.
- *"This account is already used on 3 laptops"*: `admin revoke-devices LEAD` if one is retired.
- *Caddy cannot get a certificate*: ports 80 and 443 must be open and the name must already resolve to this machine.
