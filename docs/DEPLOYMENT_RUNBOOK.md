# KisanMitra Deployment Runbook

**Two deployment targets live in this repo, and the runbook below the architecture
section documents the heavier one.** The *current* target is the free-tier
**Render + Neon + Cloudflare Pages** stack — click-by-click setup in
[RENDER_NEON_CLOUDFLARE_DEPLOYMENT.md](./RENDER_NEON_CLOUDFLARE_DEPLOYMENT.md).
It needs none of the machinery in this runbook: Render deploys from `render.yaml`,
Pages builds the frontend, and the CI/CD workflow's Oracle jobs stay skipped until
the repo variable `DEPLOY_TARGET=oracle` is set. Be honest about the split: the
free stack suits demos and the viva but **cannot deliver the heavy-load results
measured here**; this runbook's Oracle A1 shape (and everything verified against
it) is the upgrade path for real traffic.

Oracle target platform: Oracle Cloud Always Free Ampere A1 VM (ARM64, **2 OCPU /
12 GB RAM** — the entitlement was halved from 4 OCPU / 24 GB in July 2026),
Ubuntu 22.04/24.04, single host, Docker Compose, GitHub Actions, GitHub Container Registry.

## Architecture

```
GitHub push to main
  -> CI gate: secret scan, backend tests (Postgres+pgvector, Redis), frontend build, image build + Trivy scan
  -> Build multi-arch (amd64 + arm64) images -> GitHub Container Registry
  -> SSH to server -> rolling release: api-a, then api-b, then edge
  -> Health gates, smoke test, public verification, automatic rollback on failure

Internet -> (optional Cloudflare) -> Caddy edge (TLS, HTTP/3, zstd/gzip, static PWA)
         -> /api/* least-connections balancing across api-a and api-b (gunicorn + uvicorn workers)
         -> PostgreSQL 16 + pgvector, Redis 7, n8n (SSH tunnel only)
```

Releases of the API are zero-downtime (one replica is always serving). A frontend/edge
release causes a sub-two-second connection blip while the edge container restarts.

## Repository layout

```
.github/workflows/{ci.yml, cd.yml, load-test.yml}   # cd.yml gated on vars.DEPLOY_TARGET == 'oracle'
.github/dependabot.yml
.dockerignore
render.yaml                                         # Render blueprint (current target)
deploy/docker/{backend.Dockerfile, edge.Dockerfile}
deploy/caddy/Caddyfile
deploy/docker-compose.production.yml
deploy/scripts/{deploy.sh, bootstrap_server.sh, backup_postgres.sh,
                generate_secrets.sh, verify_environment.sh}
deploy/env/production.env.example                   # Oracle env template
deploy/env/render.env.example                       # Render/Neon value assembly
tests/load/locustfile.py
docs/DEPLOYMENT_RUNBOOK.md
docs/RENDER_NEON_CLOUDFLARE_DEPLOYMENT.md
docs/ORACLE_A1_PROVISIONING_AND_SECRETS.md
```

## Verified repository facts (Phase 2 audit, 2026-10-18)

These were confirmed against the code, so the deploy artifacts rely on them:

1. **ASGI entrypoint** is `backend.main:app` (not `app.main:app`). It is baked into
   `backend.Dockerfile` as the `APP_MODULE` default and overridable at deploy time.
2. **Health endpoint** is `GET /health` at the application root
   (`backend/routers/system.py`). It reports DB connectivity, model load state, and
   price-feed age. The backend itself uses no Redis; Redis serves the Telegram bot
   (FSM storage, update dedup, rate limiting) with a `MemoryStorage` fail-open fallback.
3. **Frontend** is Vite (`frontend/`, output `dist/`, `package-lock.json` present,
   `npm run lint` = oxlint). The bundle is route-code-split with `React.lazy`;
   only `TerminalView` (the landing route) stays eager.
4. **Environment variable names** are exactly what `backend/core/config.py`
   (`Settings`, pydantic-settings) reads: `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`,
   `DB_PASSWORD`, `DB_SQL_ECHO`, `DB_POOL_SIZE`, `DB_MAX_OVERFLOW`,
   `SECRET_KEY`, `CORS_ORIGINS`, `APP_ENV`, `APP_PORT`, `GEMINI_API_KEY`,
   `WHATSAPP_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID`, `WHATSAPP_VERIFY_TOKEN`,
   `WHATSAPP_APP_SECRET`, `DATA_GOV_API_KEY`, `PRICE_MAX_AGE_DAYS`, `REFRESH_ENABLED`,
   `REFRESH_INTERVAL_HOURS`, `REFRESH_LOOKBACK_DAYS`, `AGMARKNET_RESOURCE_ID`,
   `REFRESH_STATE`, `KISANMITRA_LOCK_DIR`. `DATABASE_URL` is not read; the DSN is
   composed from the `DB_*` parts. `TELEGRAM_BOT_TOKEN` / `REDIS_URL` are read by the
   Telegram bot process only.
5. **Migrations**: there is no Alembic. Schema comes from
   `scripts/00_init_db.py` (`create_all` + idempotency indexes), invoked both by the
   app lifespan and by `deploy.sh` before traffic is served. pgvector is enabled
   inside `00_init_db.py`; the models degrade gracefully when the extension is absent.
6. **API routes are NOT mounted under `/api`** — `app.include_router(api_router)` uses
   bare prefixes (`/health`, `/prices`, `/webhook`, `/auth`, …). The Caddyfile
   therefore uses `handle_path /api/*`, which strips the prefix before proxying, and
   the PWA is built with `VITE_API_URL=/api`.
7. **Cross-process lock**: the `fcntl.flock` sync lock in `/internal/sync` now honours
   `KISANMITRA_LOCK_DIR` (default `/var/lib/kisanmitra/locks`, mounted as the shared
   `api_locks` volume by compose; falls back to the system temp dir when not
   writable). The scheduled AGMARKNET refresh uses a **PostgreSQL advisory lock**
   (`data_refresh.refresh_lock`), which is replica-safe by construction: every worker
   starts the scheduler task, but only one holder fetches; losers skip their turn.
8. **Pool sizing**: `DB_POOL_SIZE` (10) + `DB_MAX_OVERFLOW` (20) per worker process.
   With `API_WORKERS=2` and 2 replicas: 30 × 2 × 2 = 120 < Postgres
   `max_connections=200`. The same formula is repeated in the compose file.
9. **`.env` is not tracked by git** and is covered by `.gitignore` (`.env`, `*.env`,
   with `production.env.example` templates instead). Startup guardrails
   (`validate_production_settings`) refuse to boot `APP_ENV=production` with missing,
   wildcard-CORS, or previously leaked secret values.

## One-time setup

> Click-by-click first-time provisioning (Oracle region choice, reserved IP, bootstrap
> via scp, firewall reconciliation) and the full secrets/`.env.production` setup are in
> [ORACLE_A1_PROVISIONING_AND_SECRETS.md](./ORACLE_A1_PROVISIONING_AND_SECRETS.md).

1. **Server.** Create an Always Free Ampere A1 VM (Ubuntu 22.04/24.04, 2 OCPU / 12 GB).
   In the VCN security list allow inbound TCP 22, TCP 80, TCP 443, UDP 443.
   If you hit "out of host capacity", retry in another AD or later — a known
   Always Free constraint, not a configuration error.
2. **DNS.** Point an A record for your domain at the server's public IP.
3. **CI key.** On your machine:
   `ssh-keygen -t ed25519 -f kisanmitra_deploy -C "github-actions-deploy" -N ""`.
4. **Bootstrap.** Copy `deploy/scripts/bootstrap_server.sh` to the server and run
   `sudo bash bootstrap_server.sh "$(cat kisanmitra_deploy.pub)"`.
5. **Environment file.** As the `deploy` user, create `/opt/kisanmitra/.env.production`
   from `deploy/env/production.env.example`; fill it using
   `bash deploy/scripts/generate_secrets.sh` (prints fresh values, writes nothing)
   plus the provider-issued tokens, then `chmod 600` it. Set `APP_ENV=production` —
   this activates the startup guardrails. `deploy.sh` runs
   `deploy/scripts/verify_environment.sh` before touching any container, so a
   placeholder, empty, wildcard-CORS, or wrong-permission env file fails fast.
6. **GitHub.** In the repository settings:
   - Secrets: `PRODUCTION_HOST`, `PRODUCTION_USER` (`deploy`), `PRODUCTION_SSH_KEY`
     (private key contents), `PRODUCTION_SSH_KNOWN_HOSTS`
     (output of `ssh-keyscan -H <host>`).
   - Variables: `PRODUCTION_DOMAIN`, and optionally `API_HEALTH_PATH`, `APP_MODULE`,
     `LOAD_TEST_READ_PATHS`, `LOAD_TEST_P95_MS`.
   - Environment: create `production` (optionally add required reviewers for manual
     approval).
   - Branch protection on `main`: require the `CI status` check.
7. **Model artifacts.** The trained models are git-ignored and never baked into
   images, so one-time copy them to the server:
   `scp data/models/{price_model.pkl,encoders.pkl,model_metadata.json}
   deploy@<host>:/var/lib/kisanmitra/data/models/` (create the directory, mode
   644). Compose bind-mounts `${MODELS_HOST_DIR:-/var/lib/kisanmitra/data/models}`
   read-only into both API replicas and sets `MODEL_DIR`; `/health` reports
   `model_loaded: true` when wired correctly. Without them the API still serves
   every feature except price forecasts (graceful error, per endpoint).
8. **Secrets hygiene.** Every credential that ever appeared in committed `.env` files
   must be rotated (WhatsApp token/verify token/app secret, Gemini key, Telegram
   token, data.gov.in key, n8n password, JWT `SECRET_KEY`, DB password). Startup
   validation rejects the known-leaked values by digest, so rotation is mandatory,
   not optional. To purge history: `git filter-repo --invert-paths --path .env --force`
   followed by a force-push and GitHub support cache invalidation.
9. **First deploy.** Push to `main`. The first run builds both images (about 15 to
   30 minutes under ARM emulation), then deploys.

## Daily operations

| Task | Command |
|---|---|
| Rollback to previous release | `bash /opt/kisanmitra/deploy/scripts/deploy.sh rollback` (on the server) |
| Redeploy a specific build | Run the **Continuous Deployment** workflow manually with `image_tag` set to a commit's first 12 characters |
| View logs | `docker compose -p kisanmitra logs -f --tail 100 api-a api-b edge` |
| Open n8n | `ssh -L 5678:127.0.0.1:5678 deploy@<host>` then browse to `http://localhost:5678` |
| Manual backup | `/opt/kisanmitra/deploy/scripts/backup_postgres.sh` |
| Load test | Run the **Load Test** workflow (weekly by default) and read the HTML report artifact |

## Capacity tuning

- Total API workers = replicas (2) × `API_WORKERS` (2). On 2 OCPU, 4 workers is the
  sensible ceiling; raise `API_WORKERS` only if the weekly load test shows CPU
  headroom.
- Keep `(DB_POOL_SIZE + DB_MAX_OVERFLOW)` × total workers below Postgres
  `max_connections` (200). Current plan: 30 × 4 = 120.
- Memory budget on 12 GB: 2 × `API_MEM_LIMIT` (3g) + Postgres (`shared_buffers` 2g,
  `effective_cache_size` 6g) + Redis (256m) + n8n + OS. Lower these first if the
  OOM killer appears in `dmesg`.
- Put the domain behind Cloudflare (free) for CDN caching, DDoS protection, and a
  rate-limiting rule on `/api/*`.
- The in-process refresh scheduler runs in every worker; the Postgres advisory lock
  makes that safe. If you prefer one place, set `REFRESH_ENABLED=false` on the API
  and drive `scripts/refresh_prices.py` from the existing systemd timer instead.
- Treat the weekly load test as the capacity baseline. Tune `LOAD_TEST_P95_MS` and
  the user count to reflect expected farmer traffic.

## Measured capacity baseline (2026-10-18, constrained local validation)

Shape: 2 API replicas × 2 gunicorn/uvicorn workers, models loaded, Caddy edge in
front, Postgres with the production defaults, Redis 7, n8n. CPU was cgroup-limited
to **2.0 cores total** (faithful to the A1); memory limits were scaled down
(7 GB dev host cannot allocate 12 GB) so per-container peak RSS was measured and
compared against the 12 GB budget analytically.

| Run | Result |
|---|---|
| Heavy load: 150 users, spawn 15/s, 3 min through the edge | 20,972 requests, **0 failures (0.00%)**, ~117 req/s, p50 2 ms, p95 4 ms, p99 13 ms, max 84 ms |
| Peak RSS per container (during heavy load) | api-a 660 MiB, api-b 649 MiB, edge 68 MiB, postgres 65 MiB*, redis 6 MiB, n8n 237 MiB — **stack total ≈ 1.7 GiB** |
| 15-min soak, 50 users (32 samples) | 35,839 requests, **0 failures**, ~40 req/s, p95 5 ms; per-container RSS flat or falling over the run (api 648 MiB peak, sawtooth from `--max-requests` worker recycling) — no leak signature |
| Rolling release under 150-user load (`deploy.sh`, TLS) | release live in 26 s (api-a → api-b → edge, smoke attempt 1); 28,189 requests, 74 failures = **0.26%** (threshold 1%), all transient `SSLEOFError` keepalive resets while the edge container swapped; p95 stayed 5 ms, worst in-flight request 1.03 s |

Decision rule check: peak total ≈ 1.7 GiB ≪ 10 GiB; p95 ≤ 5 ms ≪ 800 ms; failures ≤ 0.26% <
1% — no production default was changed. Two replicas × 2 workers stay.

*Postgres RSS is small because the validation database holds only schema, not
years of mandi prices; its steady-state size is dominated by `shared_buffers +
work_mem × connections`, all bounded by the compose settings. Against the 12 GB
budget the measured stack is ~1.7 GiB (limits allow 3g×2 + headroom); no default
needed to change. The real 12 GB ceiling remains unverified off-Oracle — confirm
once on the VM with `docker stats` during the first weekly load test.

## Oracle Always Free operating rules

- **Never upgrade the account to Pay As You Go.** Overages above the free
  entitlement (1,500 OCPU-hours + 9,000 GB-hours/month total across ALL A1
  instances — currently one 2 OCPU / 12 GB VM) are billed to the card.
- **"Out of host capacity" on instance create is common** and is not a
  configuration error: retry at different times of day, try every availability
  domain in the region, and retry from the Console *and* `oci` CLI. A spare
  always-free `BM.Standard.A1` reservation, if your tenancy allows, does not
  exist retroactively — keep the retry cadence instead.
- **Idle reclamation:** Always Free tenancies are flagged for utilization under
  ~20% CPU/memory average over 7 days. The weekly load test and the hourly
  AGMARKNET refresh keep usage above the floor; if you pause the stack,
  upgrade nothing — just re-provision from this runbook.
- Keep total footprint within the free tier: one A1 VM + block volume (200 GB
  free aggregate) + 10 TB egress/month. Cloudflare's free tier absorbs most
  static egress.

## Free-tier stack: Render + Neon + Cloudflare Pages (current target)

This is no longer a "fallback" — it is the deployment the project runs on today,
documented end-to-end in
[RENDER_NEON_CLOUDFLARE_DEPLOYMENT.md](./RENDER_NEON_CLOUDFLARE_DEPLOYMENT.md).
Key deltas from everything above, verified against provider docs on 2026-10-18:

- **API:** Render free Docker web service (0.1 CPU / 512 MB, single worker,
  spins down after 15 min idle, ~1 min cold start, 750 instance-hours/month,
  ephemeral filesystem — `MODEL_DIR` and friends live under `/tmp`).
- **Database:** Neon Free Postgres (1 GB storage/project, scale-to-zero after
  5 min). SSL required (`DB_SSLMODE=require`); use the **direct** endpoint —
  the pooled PgBouncer endpoint is transaction-mode and breaks the
  session-level advisory refresh lock. The backend now carries a small pool
  (3+2), `pool_recycle=300`, and a bounded connect retry for Neon wake-ups.
- **Models:** 57.2 MB total — not committed, not in the image; downloaded at
  startup from `MODEL_URL` and **refused unless the SHA-256 matches**.
- **Frontend:** Cloudflare Pages with `frontend/public/_redirects` and
  `_headers`; `VITE_API_URL` is a Pages **build-time** variable pointing at
  the Render origin (the committed `/api` value only works behind Caddy).
- **CI/CD:** `cd.yml`'s Oracle jobs skip unless `DEPLOY_TARGET=oracle`; Render
  and Pages deploy from their own dashboards/blueprint, not from GitHub Actions.
- **What does NOT fit:** n8n (no always-on container), the Telegram bot as a
  Render process (free tier has no background workers — run it locally with
  polling against the deployed API), heavy-load claims, and 24/7 low-latency
  WhatsApp webhooks (first delivery after idle sees the cold start; Meta
  retries, so messages arrive late rather than lost). The in-process scheduler
  with `catch_up_on_start` refreshes stale prices automatically whenever the
  service wakes.

## Demo channel: Telegram first

WhatsApp production access needs Meta Business Verification and template
approval (days to weeks). The Telegram bot (`telegram_bot/`) exercises the same
message handler, RAG, price, and declaration pipeline through
`/webhook`-equivalent long polling and is the demo channel until WhatsApp
approval lands. Set `TELEGRAM_BOT_TOKEN` + `TELEGRAM_WEBHOOK_URL` (or run the
bot with polling) and share the bot handle. Both channels are fail-open with
respect to Redis: with no reachable Redis the bot falls back to
`MemoryStorage` and the middleware skips its checks (verified in
`telegram_bot/bot.py`; the fallback and the backend's complete independence
from Redis — zero references in `backend/` — were both exercised live on
2026-10-18 by stopping the Redis container under load with the API and edge
remaining healthy).
