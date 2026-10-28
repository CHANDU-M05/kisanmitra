# KisanMitra — Oracle A1 Provisioning & Production Secrets Checklist

Click-by-click runbook for standing up the Oracle Always Free ARM64 host, pointing
DNS at it, and filling in the production secrets the deploy workflow expects.

Companion to [DEPLOYMENT_RUNBOOK.md](./DEPLOYMENT_RUNBOOK.md) (architecture, daily
operations, capacity baseline, and Oracle idle-reclamation rules). This file covers
only the **first-time** provisioning + secret setup. The deploy path is `deploy/`
(Docker Compose + Caddy); the `deployment/` nginx/systemd tree is a separate,
non-CI path and is not used by `cd.yml`.

**Status of every remote side here is UNVERIFIED from the dev machine** — Oracle
capacity, DNS propagation, and provider rotation must be confirmed by the operator.

---

## Part A — Oracle A1 VM + DNS

### A0. Choose the region BEFORE you sign up
- The **home region is permanent** once the account exists; you cannot change it later.
- **Mumbai (`ap-mumbai-1`) or Hyderabad (`ap-hyderabad-1`)** give the lowest latency from
  Bangalore, but A1 free capacity is scarcer in busy regions.
- Current A1 capacity cannot be checked from here. If you **already have an account**,
  you are locked into its home region — rely on the retry rules in A1 instead.

### A1. Compute instance (Console → Compute → Instances → Create)
1. Name `kisanmitra-prod`.
2. **Image**: Ubuntu 24.04 (**aarch64 / ARM**).
3. **Shape**: Ampere → `VM.Standard.A1.Flex`, set **OCPUs = 2, RAM = 12 GB**.
   - Matches the halved 2026 Always-Free entitlement sized in
     `deploy/env/production.env.example` (capacity block).
4. **Network**: the public subnet of your VCN (create one via A2 if none exists).
   Check **Assign a public IPv4 address**.
5. **Boot volume**: **150 GB** (paravirtual). Free tier allows 200 GB block storage total,
   leaving headroom for Docker images, Postgres data, and model artifacts.
6. **SSH keys**: create/download an **admin** key (e.g. `kisanmitra-admin.pem`). This is
   yours for interactive login — it is *not* the CI key (see A5).
7. Create; wait for **RUNNING**.
8. **Ephemeral vs reserved IP**: the auto-assigned public IP is *ephemeral* — it survives
   stop/start but is **released on terminate**. Convert to a **Reserved Public IP** so you
   can re-create the VM later without touching DNS.
9. **Retry rules for "Out of host capacity"**: retry at a different time of day, try
   another availability domain, or use a different ARM-enabled region. This is the most
   common Always-Free failure and is transient.

### A2. Networking / OCI firewall (Console → VCN → Public Subnet → Security List)
Add stateful **Ingress** rules `0.0.0.0/0` for:
- `22/tcp` (SSH)
- `80/tcp`  (HTTP — Let's Encrypt HTTP-01 + redirect)
- `443/tcp` (HTTPS)
- `443/udp` (HTTP/3 / QUIC — Caddy serves `h1 h2 h3`)

> The **OCI Security List is separate from the host firewall** (`ufw`). Both must allow
> 80/443, otherwise Caddy's TLS issuance silently fails. See A6.

### A3. Copy the bootstrap script to the server (do NOT curl it from GitHub)
Use `scp` from your **reviewed local checkout**. A raw-URL fetch fails if the repo is
private, and it makes a root shell run whatever is at the branch head at that moment.

```bash
# from your local repo, after reviewing deploy/scripts/bootstrap_server.sh
scp deploy/scripts/bootstrap_server.sh ubuntu@<RESERVED_PUBLIC_IP>:/tmp/bootstrap.sh
```

### A4. Generate the CI keypair on YOUR machine
```bash
ssh-keygen -t ed25519 -N "" -f ~/.ssh/kisanmitra_ci -C "ci@kisanmitra"
```
`-N ""` sets an **empty passphrase** — required, because GitHub Actions cannot answer an
interactive passphrase prompt, so a passphrase-protected key fails the SSH deploy step.
- **Public half** (`~/.ssh/kisanmitra_ci.pub`) → goes into the bootstrap command (A5).
- **Private half** (`~/.ssh/kisanmitra_ci`) → ONLY into the GitHub `PRODUCTION_SSH_KEY`
  secret (Part B). **Never paste a private key into a chat, ticket, or to the agent.**

### A5. Run the bootstrap (ON the server, as root)
`bootstrap_server.sh` installs Docker + the compose plugin, creates the `deploy` user and
`/opt/kisanmitra`, configures `ufw`, fail2ban, unattended-upgrades, 4 GB swap, sysctl
tuning, Docker log rotation, and a nightly 21:00 UTC Postgres backup cron.

```bash
ssh -i kisanmitra-admin.pem ubuntu@<RESERVED_PUBLIC_IP>
sudo bash -c '
  export DEPLOY_PUBLIC_KEY="<contents of ~/.ssh/kisanmitra_ci.pub>"
  bash /tmp/bootstrap.sh
'
```
It prints the server public IP at the end — confirm it equals your reserved IP.
The script reads the key from the `DEPLOY_PUBLIC_KEY` **environment variable** (not a
positional argument) and appends it to `deploy`'s `authorized_keys` — see
`deploy/scripts/bootstrap_server.sh` line 75 — so the `export` above is correct.

### A6. Reconcile OCI firewall + host firewall + image iptables
Oracle Ubuntu images ship their own `iptables` rules that can **block a port even after
`ufw` allows it**. From **outside** (laptop, or phone on mobile data — not the VM itself):
```bash
nc -vz <RESERVED_PUBLIC_IP> 80
nc -vz <RESERVED_PUBLIC_IP> 443
```
**Read the result correctly before the first deploy:** nothing listens on 80/443 until
Caddy starts, so both `succeeded` and `connection refused` mean the **firewall is open**
(the probe reached the host). Only a **timeout** (`Ncat: Connection timed out`) means a
firewall is silently dropping the packet. Port 22 always listens, so use it as the control:
if 22 also times out, a firewall layer is blocking. Re-run this after the deploy for a
positive "listening" result on 80/443.
If a port times out, inspect for a REJECT/DROP sitting above the allow rules:
```bash
sudo iptables -L INPUT -n --line-numbers
```
Fix the lowest layer that is blocking (OCI Security List → host `iptables` → `ufw`), so
all three agree on 22/80/443 + 443/udp.

### A7. DNS
1. Create an **A record** for your `DOMAIN` (e.g. `@`/`app`) → `<RESERVED_PUBLIC_IP>`.
2. Verify propagation: `dig +short <DOMAIN>` returns that IP.
3. Do **not** request a certificate manually — Caddy auto-issues via Let's Encrypt on the
   first `deploy.sh` run, which needs `80/tcp` reachable end-to-end (A6).

### A8. Pre-merge sanity checks
- `sudo -u deploy docker ps` works (deploy user is in the `docker` group).
- `ssh -i ~/.ssh/kisanmitra_ci -o BatchMode=yes deploy@<HOST> 'echo ok'` prints `ok`
  with **no password prompt** — this is exactly how `cd.yml` connects.
- `.env.production` created and passing the gate (Part B).

---

## Part B — GitHub secrets, `production` environment, and `.env.production`

### B1. GitHub Actions configuration (Settings → Secrets and variables → Actions)
From `.github/workflows/cd.yml`, the deploy job needs exactly these (values only, never
private keys pasted in chat — add them through the GitHub UI):

| Type | Name | Value |
|---|---|---|
| Secret | `PRODUCTION_HOST` | reserved public IP (or hostname) |
| Secret | `PRODUCTION_USER` | `deploy` |
| Secret | `PRODUCTION_SSH_KEY` | **private** key `~/.ssh/kisanmitra_ci` (public half went into A5) |
| Secret | `PRODUCTION_SSH_KNOWN_HOSTS` | `ssh-keyscan -t ed25519,rsa <HOST>` output |
| Variable | `PRODUCTION_DOMAIN` | the `DOMAIN=` set in `.env.production` |
| Variable | `API_HEALTH_PATH` | `/health` |

- **GHCR**: no secret needed — `cd.yml` logs in with the built-in `GITHUB_TOKEN`
  (`packages: write`). Image prefix must be **lowercase**:
  `ghcr.io/chandu-m05/kisanmitra/backend` and `.../edge` (the `prepare` job lowercases it).
- **`production` environment**: create it, then add **yourself as a required reviewer** so
  the deploy job waits for manual approval. This is the safety gate if you merge before the
  server is fully ready.

### B2. Generate the app's own secrets (on YOUR machine)
`cd.yml` only copies `deploy/scripts/` to the server **during** a deploy, so
`generate_secrets.sh`, `verify_environment.sh`, and `production.env.example` do **not**
exist on the server before the first deploy. Build `.env.production` locally instead —
this also keeps the secrets out of the server's shell history. Run the helper from your
local checkout; it prints `KEY=value` to stdout, never writes to the repo, never logs
values:
```bash
bash deploy/scripts/generate_secrets.sh
```
It produces fresh values for: `SECRET_KEY` (64 hex), `DB_PASSWORD`, `REDIS_PASSWORD`,
`N8N_ENCRYPTION_KEY`, `WHATSAPP_VERIFY_TOKEN`.

### B3. Rotate the third-party credentials at their providers (cannot be generated)
These **must be brand-new values** — never reuse anything that was ever committed or
appeared in a diff/chat. Treat all scrubbed history values as burned:

| Variable | Provider |
|---|---|
| `WHATSAPP_TOKEN` | Meta Business / WhatsApp Cloud API (permanent token) |
| `WHATSAPP_APP_SECRET` | Meta app dashboard (required for webhook HMAC verify) |
| `WHATSAPP_PHONE_NUMBER_ID` | Cloud API setup page |
| `TELEGRAM_BOT_TOKEN` / `TELEGRAM_WEBHOOK_SECRET` | @BotFather |
| `GEMINI_API_KEY` | Google AI Studio (optional) |
| `DATA_GOV_API_KEY` | data.gov.in (optional) |

Rotating `SECRET_KEY` invalidates all outstanding JWTs (signs everyone out) — that is the
intended effect.

### B4. Assemble locally (outside the repo), then place `/opt/kisanmitra/.env.production`
Fill every value in a **local copy** of the template. Build it in a temp dir **outside the
repo working tree** — `.gitignore` matches `.env.*` and `*.env` but **not** an arbitrary
name like `kisanmitra.env.production`, so a stray secret file inside the repo could get
committed. **Variable names must match `backend/core/config.py`** (the Settings class is
the authority):
```bash
# on your machine — assemble OUTSIDE the repo so a secret file can never be committed
umask 077
ENVWORK="$(mktemp -d)"
cp deploy/env/production.env.example "$ENVWORK/.env.production"
# ...fill B2 + B3 values in "$ENVWORK/.env.production", then validate it locally (B5)...

# transfer it up, install it owned by deploy (mode 600), then destroy the server /tmp copy
scp "$ENVWORK/.env.production" ubuntu@<RESERVED_PUBLIC_IP>:/tmp/env.production
ssh -i kisanmitra-admin.pem ubuntu@<RESERVED_PUBLIC_IP> '
  sudo install -o deploy -g deploy -m 600 /tmp/env.production /opt/kisanmitra/.env.production
  shred -u /tmp/env.production 2>/dev/null || rm -f /tmp/env.production
'

# once the file is safely on the server, destroy the local copy too
shred -u "$ENVWORK/.env.production" 2>/dev/null || rm -f "$ENVWORK/.env.production"
rmdir "$ENVWORK"
```
Notes:
- `install -o deploy -g deploy -m 600` sets ownership **and** mode in one step (equivalent
  to `chown deploy:deploy` then `chmod 600`). Do **not** `sudo cp` a root-owned file and
  `sudo -u deploy vi` it: `deploy.sh` runs as `deploy` and cannot read a root-owned
  mode-600 file.
- The `scp` lands a **plaintext** copy in the world-readable `/tmp`; shred/`rm` it (and the
  local copy) immediately so no secret lingers on disk. `shred` is best-effort on
  journaling/COW filesystems — `rm` is the fallback.

Key constraints to get right (enforced downstream):
- `APP_ENV=production` (must be exactly this string).
- `SECRET_KEY` ≥ 32 chars and **not** a previously leaked value.
- `DOMAIN`, `ACME_EMAIL`, `API_HEALTH_PATH=/health` — edge routing.
- `CORS_ORIGINS` must list the explicit origin equal to `DOMAIN`; **no wildcard**.
- `DB_HOST=postgres`, `DB_PORT=5432`, `DB_NAME`, `DB_USER`, `DB_PASSWORD` — do not change
  the host/port; those are Compose service names.
- `REDIS_PASSWORD` **and** the password embedded in `REDIS_URL`
  (`redis://:<same>@redis:6379/0`) must match.
- `WHATSAPP_VERIFY_TOKEN`, `WHATSAPP_APP_SECRET` present and non-placeholder.
- `REFRESH_ENABLED`/`REFRESH_*`, and capacity knobs (`API_WORKERS=2`, `API_MEM_LIMIT=3g`,
  `PG_SHARED_BUFFERS=2GB`, `PG_EFFECTIVE_CACHE_SIZE=6GB`, `REDIS_MAXMEMORY=256mb`) sized for
  12 GB — see the baseline in DEPLOYMENT_RUNBOOK.md.
- `BACKEND_URL=http://api-a:8000` (internal). n8n is **not** published — reach it via
  `ssh -L 5678:127.0.0.1:5678 deploy@<HOST>`.

### B5. The `verify_environment.sh` pre-deploy gate
`deploy.sh` runs this **before touching any container** and aborts on any failure. Run it
**locally against your assembled file** before scp-ing it up (the script is not on the
server until the first deploy; it never prints secret values):
```bash
bash deploy/scripts/verify_environment.sh "$ENVWORK/.env.production"
```
Checks performed:
- File exists; **permissions `600` or `400`**.
- All required vars present **and non-empty**: `APP_ENV DOMAIN ACME_EMAIL SECRET_KEY
  CORS_ORIGINS DB_HOST DB_PORT DB_NAME DB_USER DB_PASSWORD REDIS_PASSWORD
  N8N_ENCRYPTION_KEY WHATSAPP_VERIFY_TOKEN WHATSAPP_APP_SECRET`.
- **No placeholder values** (`replace-with*`, `changeme`, `your-*`, `TODO*`, `xxxx*`, `<…>`).
- `APP_ENV == production`; `SECRET_KEY` length ≥ 32; `CORS_ORIGINS` has no `*`;
  `DOMAIN` looks like a public hostname.

Passing this gate is necessary but not sufficient: at app start
`validate_production_settings()` also **refuses known-leaked credentials by SHA-256
digest** (fail-closed), so a host still using any old value will not boot.

### B6. Order of operations
1. Part A complete (VM up, ports open, DNS resolving, CI key handshake works).
2. B2 + B3 locally → assemble `.env.production` (B4).
3. B5 gate passes **locally**, then scp the finished file up and `install` it as deploy.
4. B1 secrets/vars + `production` environment (required reviewer) in GitHub.
5. Branch protection: require `CI status` on `main`.
6. Only then merge PR #1 → the first `push: main` is a real deployment.

### B7. Housekeeping after a verified deploy
- Delete the pre-scrub backup folder `/home/chandu/kisanmitra-git-backup-prescrub-20261018/`
  (it still contains the old secrets; never push it).
- (Optional hardening) pin third-party actions to full commit SHAs; Dependabot already
  watches GitHub Actions.
- Open a GitHub support request to purge PR #1's pre-rewrite commit refs (opened before the
  history scrub, so old blobs may linger via the PR ref / direct-SHA links until GC).
