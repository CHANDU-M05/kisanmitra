# KisanMitra — Render + Neon + Cloudflare Pages Deployment Guide

**Status:** current target for the demo/viva deployment (verified 2026-10-18).
**Honest scope:** this free-tier stack is for demos, evaluation, and the viva —
it **cannot** serve the heavy-load goal measured in the Oracle runbook. Render
free gives 0.1 CPU / 512 MB RAM, spins the service down after 15 minutes idle
(~1 min cold start), and allows 750 instance-hours per month with an *ephemeral
filesystem*. The Oracle A1 stack in `deploy/` stays in the repo, untouched, as
the documented upgrade path.

Plan-of-record at a glance:

| Piece | Service | What runs there |
|---|---|---|
| API | Render free **Docker** web service (`render.yaml`) | `backend.main:app`, gunicorn, 1 worker |
| Database | Neon Free Postgres (1 GB/project) | all persistent state + pgvector |
| Frontend | Cloudflare Pages (free, unlimited bandwidth) | built Vite PWA from `frontend/` |
| Models | your object download + SHA-256 pin | fetched into `/tmp` at boot, verified |
| Telegram bot | **not** on Render free (no background workers) | run locally with polling, or skip |

---

## 0. Before you start — what you must rotate

Every secret that ever appeared in a committed `.env` must be rotated *before*
pasting it into any of these dashboards. The app refuses to boot in production
with known-leaked values (digest registry `is_known_compromised_secret` in
`backend/core/config.py`, enforced by `validate_production_settings`), so this
is mandatory, not advice. Rotate: WhatsApp token / app secret / verify token,
Gemini key, Telegram token, data.gov.in key, JWT `SECRET_KEY`, DB password.

Reference variable names in docs and tickets — never paste values anywhere.

## 1. Neon (database first — everything else needs its endpoint)

1. Sign up at https://neon.tech (GitHub login is fine), create a project.
   **Postgres version:** Neon now defaults new projects to Postgres **18**
   and runs 18.6 — the exact same major/minor as the local source database
   (host PostgreSQL 18.6, `pg_dump` 18.6, verified 2026-10-18). Accept the
   default; do not pick 16 or 17. Fallback only if the SQL-editor
   `CREATE EXTENSION vector;` step errors on 18: recreate the project on 17
   and re-check before dumping.
   **Region:** choose **AWS Singapore (`aws-ap-southeast-1`)** so Neon
   shares one region with the Render service (§3). Render's regions doc
   lists Singapore as a normal service region and nowhere restricts the
   free plan to the US (checked 2026-10-18: render.com/docs/regions —
   Oregon, Ohio, Virginia, Frankfurt, Singapore). For users in India this
   makes both hops short: user→Render(Singapore)→Neon(Singapore), with
   static assets already served from the Cloudflare edge. If for any
   reason Render's free tier is not offered in Singapore at creation
   (§3 dashboard check), put Neon in whichever cloud region matches the
   Render region you got — **the two must always match**, and Frankfurt
   is the next-best distance from India, ahead of the US.
2. Neon creates a database (`neondb`), a role, and a password. On the
   **Connection Details** page copy the **non-pooled / direct endpoint**
   (looks like `ep-…-pooler` **without** the `-pooler` suffix — the *pooled*
   string is the one with `-pooler` in the hostname).
   - **Use the direct endpoint, not the pooled one.** The pooled endpoint is
     PgBouncer in *transaction* mode, which breaks two things this app needs:
     the session-level `pg_try_advisory_lock` refresh lock
     (`backend/services/data_refresh.py`) and any per-session configuration.
     The app's pool is already tiny (3+2), so pooling adds little here.
3. SSL is mandatory — leave "Pooled"/"SSL enabled" as Neon presents it; the
   app enforces TLS via `DB_SSLMODE=require` (set in `render.yaml`).
4. pgvector: Neon ships the extension; `scripts/00_init_db.py` (run by the app
   lifespan) executes `CREATE EXTENSION IF NOT EXISTS vector` itself.
5. Scale-to-zero: the Free plan sleeps the compute after 5 minutes idle and
   **cannot** disable it. That is fine — the backend retries connects with
   bounded backoff (`DB_CONNECT_RETRIES`, `ensure_database_reachable()`), and
   the first query pays a ~500 ms–2 s wake.

### Restore your data

Neon is ordinary Postgres, so the migration is one dump and one restore.
Check the size first — the Free plan cap (1 GB/project per current Neon
docs, verified 2026-10-18) is not a blocker here: the live database measures
**20 MB** (`mandi_prices` ≈ 11 MB being the largest table).

```bash
# 0. Size check (informational; 20 MB as of 2026-10-18)
psql -h localhost -U <user> -d kisanmitra -tA -P pager=off -c \
  "SELECT pg_size_pretty(pg_database_size(current_database()));"

# 1. In the Neon SQL editor, before restoring (the local DB has only plpgsql,
#    so the extension is not in the dump — create it here instead):
#    CREATE EXTENSION vector;

# 2. Dump locally with a pg_dump matching the server major (host PG 18)
pg_dump -Fc --no-owner --no-acl -h localhost -U <user> -d kisanmitra -f kisanmitra.dump

# 3. Restore into the DIRECT endpoint (not the -pooler one), password via prompt
pg_restore --no-owner --no-acl -d "<neon-direct-connection-string>" kisanmitra.dump

# 4. Remove the dump — it holds your data
shred -u kisanmitra.dump
```

The restored dump replaces `scripts/00_init_db.py`'s schema creation — do not
run both (the app's `create_all` is idempotent, but the restore is the source
of truth). `--no-owner --no-acl` restore output routinely prints warnings
about roles or extensions — those are expected; only real `ERROR` lines
naming a table matter. One caveat found during the size check:
`knowledge_chunks` is **empty locally**, so no RAG embeddings travel in the
dump. After restoring, rebuild the RAG content against Neon —
`scripts/seed_knowledge.py` then `scripts/backfill_embeddings.py` (embeddings
need a Gemini key: use the **rotated** one, never the old committed key) —
before testing the advisory path. Then confirm the wiring:
`curl https://<service>.onrender.com/health` must show
`database_connected: true`.

## 2. Model archive (Render's filesystem is ephemeral)

The trained models total **57.2 MB** (`price_model.pkl` 57,232,006 B +
`encoders.pkl` + `model_metadata.json`) — above the ~50 MB commit threshold,
so they are **not** in git and **not** in the Docker image (`.dockerignore`
drops `data/`). The backend downloads a `tar.gz` at startup into
`MODEL_DIR=/tmp/kisanmitra/models` and **refuses to un-pickle it unless the
SHA-256 matches `MODEL_SHA256`** (`backend/services/ml_service.py`).

Build the archive once, on the machine that has the models:

```bash
cd data/models
tar czf kisanmitra-models.tar.gz price_model.pkl encoders.pkl model_metadata.json
sha256sum kisanmitra-models.tar.gz    # → paste this as MODEL_SHA256
```

Host the tarball on any HTTPS URL the app can fetch with a plain
unauthenticated GET (`urllib.request.urlopen`, no `Authorization` header).
Any such URL works — including a presigned object link, whose signature
rides in the URL itself — but the options below need **no payment card**,
which the free-tier plan requires. The weights are trained on public mandi
data, so hosting them publicly is fine; what protects you is the
`MODEL_SHA256` check — pickles can execute arbitrary code when loaded, so
the hash pin is what stops a swapped file, and it must never be skipped.

1. **Hugging Face Hub model repo (recommended)** — public, free, no card,
   built for model weights: create a model repo, upload the archive, and
   use `https://huggingface.co/<user>/<repo>/resolve/main/<file>.tar.gz`
   as `MODEL_URL`.
2. **A separate small public GitHub repo with a Release** holding just the
   archive — works the same way, hash pin protecting integrity.
3. **A Release asset in the main repo — only if this repo is public.**
   A private repo's release assets are private too: the anonymous download
   returns 404, the app boots with forecasting off, and `/health` shows
   `model_status: "failed"`. Check the repo's visibility in Settings
   before choosing this.

If `MODEL_URL` or `MODEL_SHA256` is missing, the app still boots and every
non-forecast feature works — check `/health` on the first deploy so a
silent forecasting outage is not mistaken for success.

## 3. Render (the API)

1. Sign up at https://render.com (GitHub login).
2. Dashboard → **New → Blueprint** → pick this repo → Render reads
   `render.yaml` and proposes the `kisanmitra-api` service.
3. **Region:** `render.yaml` sets `region: singapore` (valid per
   render.com/docs/blueprint-spec, checked 2026-10-18; Neon's cloud
   counterpart is AWS `aws-ap-southeast-1`). A service's region **cannot
   be changed after creation**, so this is a get-it-right-once decision.
   Render's docs do not state free-tier region availability — **check in
   the dashboard** that Singapore is offered when the Blueprint creates the
   Free instance. If it is not, edit `render.yaml` to the closest allowed
   region — prefer `frankfurt` over the US options for proximity to India —
   recreate the Neon project in the matching cloud region, and re-apply the
   Blueprint.
4. Blueprint creation asks for each `sync: false` secret — fill in
   `SECRET_KEY`, `DB_HOST` (direct endpoint), `DB_PORT` (5432), `DB_NAME`,
   `DB_USER`, `DB_PASSWORD`, `CORS_ORIGINS`, `MODEL_URL`, `MODEL_SHA256`.
   `CORS_ORIGINS` must be the exact Pages origin, e.g.
   `https://kisanmitra.pages.dev` (comma-separate more origins; no `*` —
   production config validation rejects wildcards). Leave WhatsApp/Telegram/
   Gemini keys empty for now if you don't need those channels yet; the app
   degrades per-feature, not at boot.
5. Do **not** add a `PORT` env var — Render injects it and the image binds
   `${PORT:-8000}`. Hard-coding it breaks routing (comment in `render.yaml`).
6. After creation: Service → Settings → **Wait for CI to pass before deploy**
   (GitHub App authorization required) — this makes Render honor your CI check
   instead of deploying the raw push. Keep the `/health` health check; it
   reports `model_status` while the model warms in the background, and the
   server answers requests before the model is loaded (predictions return a
   clear 503-style "still loading" until ready).
7. Expect: first deploy 5–10 min (Docker build), cold starts ~60 s after 15
   min idle, and an email when you approach 750 instance-hours.

### Demo-warming (optional, honest caveat)

A cron hitting `/health` every 10 minutes keeps the service warm for a demo
window but burns ~1/6 of your free instance-hours per day it's enabled.
Turn the pinger on the morning of the demo, off afterwards — do not run it
24/7 "just in case".

## 4. Cloudflare Pages (the frontend)

1. Sign up at https://pages.cloudflare.com → **Create a project** → connect
   the same GitHub repo.
2. Build settings:
   - Framework preset: none. Build command: `cd frontend && npm ci && npm run build`
   - Output directory: `frontend/dist` (set "Root directory" to the repo root;
     Pages accepts the nested output path).
3. Environment variables — add for **Production**:
   - `VITE_API_URL` = `https://<your-service>.onrender.com`
     This is a **build-time** variable: Vite bakes it into the bundle via
     `frontend/src/config.js` (`import.meta.env.VITE_API_URL`). It overrides
     the committed `frontend/.env.production` (`VITE_API_URL=/api`, which is
     correct only for the Oracle same-origin Caddy setup) because Vite honors
     real process env over `.env` files.
4. The repo ships `frontend/public/_redirects` (SPA fallback
   `/* /index.html 200`) and `frontend/public/_headers` (immutable caching for
   hashed `/assets/*`, `no-cache` for `index.html`/`sw.js`/`registerSW.js`/
   `manifest.webmanifest`/`workbox-*.js`, and the same security headers Caddy
   sets). Vite copies `public/` into `dist/` — nothing else to configure.
5. Deploy, then check a deep link (e.g. `/farmers`) reloads without a 404 and
   DevTools shows `Cache-Control: immutable` on `/assets/*`.
6. CORS: the API must see your exact origin in `CORS_ORIGINS` (§3.4). If you
   add a custom Pages domain, append it to `CORS_ORIGINS` on Render and
   redeploy the env change (~1 min).

## 5. Messaging channels on this stack (what actually works)

- **WhatsApp webhooks:** functional but cold-start-sensitive — after 15 min
  idle, Meta's first delivery fails fast and retries; expect seconds-to-minutes
  latency on the *first* message after idleness, not lost messages.
- **Telegram bot:** needs a long-lived process (polling) or a webhook receiver.
  Render free has **no background workers** (worker services are paid), so the
  bot does **not** run on this stack. Run it locally for the demo
  (`python -m telegram_bot.bot`, polling mode — no public URL needed), or on
  any always-on host. It talks to the Render API through the same
  `backend_client`, so a live demo from your laptop works.
- **n8n:** does not fit free tiers at all (needs an always-on container). The
  in-process AGMARKNET scheduler replaces it here: `REFRESH_ENABLED=true`,
  every 6 h, and it **catches up on boot if the feed is stale**, so a service
  waking from spin-down refreshes old prices on its first minutes — no cron
  needed (verified: `backend/services/scheduler.py`, `catch_up_on_start`).

## 6. What to verify after everything is up

```bash
curl -s https://<render>/.                     # version + model_loaded
curl -s https://<render>/health | python3 -m json.tool
# expect: database:true, model_status:"ready" (after warmup),
#         price_feed_age_days within PRICE_MAX_AGE_DAYS=3
curl -sI https://<pages>.pages.dev/ | grep -i cache-control   # no-cache
curl -sI https://<pages>.pages.dev/assets/<hashed>.js | grep -i cache-control  # immutable
curl -s -H "Origin: https://<pages>.pages.dev" \
  https://<render>/prices | head -c 200        # 200 + Access-Control-Allow-Origin
```

Then open the Pages URL in a browser and check a price query round-trips.

## 7. Upgrade path (later, deliberately)

When the demo phase ends and heavy load matters again, the Oracle A1 stack is
unchanged in this repo. Enabling it is three moves: provision the VM
(`docs/ORACLE_A1_PROVISIONING_AND_SECRETS.md`), set the repo variable
`DEPLOY_TARGET=oracle` (`gh variable set DEPLOY_TARGET --body oracle`) — which
re-arms the `build`/`deploy` jobs in `.github/workflows/cd.yml`, disabled by
default since this stack does not use them — and point DNS at Caddy instead of
Pages. The Render service can keep running as a staging API meanwhile.
