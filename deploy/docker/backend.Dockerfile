# KisanMitra backend (FastAPI) production image.
# Build context: repository root (required — requirements.txt is at the root).
#
# The backend directory is copied to /app/ in the runtime stage.
# Gunicorn is invoked as:  gunicorn backend.main:app  (entrypoint is the Python package)
#
# ASGI entrypoint: backend.main:app  (matches repository layout and settings class)

# ── Stage 1: build Python wheels ──────────────────────────────────────────────
FROM python:3.12-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential libpq-dev \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:${PATH}"

# requirements.txt is at the repository root, not inside backend/
COPY requirements.txt /tmp/requirements.txt
RUN pip install -r /tmp/requirements.txt \
    && pip install "gunicorn>=22.0" "uvicorn[standard]>=0.30"

# ── Stage 2: lean runtime image ───────────────────────────────────────────────
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:${PATH}" \
    # Overridable at deploy time via docker-compose environment:
    APP_MODULE="backend.main:app" \
    # Default to a single worker: Render's free 512 MB / 0.1 CPU plan cannot
    # afford the ~350 MB-per-worker model footprint at WEB_CONCURRENCY=2. The
    # Oracle/compose stack overrides this to 2 via its environment.
    WEB_CONCURRENCY=1 \
    # Shared lock path for multi-container flock synchronisation.
    # Must match the volume mount in docker-compose.production.yml.
    KISANMITRA_LOCK_DIR="/var/lib/kisanmitra/locks" \
    KISANMITRA_LOG_DIR="/var/lib/kisanmitra/logs"

RUN apt-get update \
    && apt-get install -y --no-install-recommends libpq5 \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --system --uid 10001 --create-home appuser \
    && mkdir -p /var/lib/kisanmitra/locks /var/lib/kisanmitra/logs \
    && chown -R appuser:appuser /var/lib/kisanmitra

COPY --from=builder /opt/venv /opt/venv

WORKDIR /app

# Copy entire repo so that `backend`, `scripts`, and `data` packages are reachable.
# .dockerignore removes secrets, caches, node_modules, etc.
COPY --chown=appuser:appuser . /app/

USER appuser
EXPOSE 8000

# max-requests + jitter recycles workers to prevent memory growth from the RF model.
# graceful-timeout gives active requests time to complete before worker replacement.
CMD ["sh", "-c", \
     "exec gunicorn ${APP_MODULE} \
        -k uvicorn.workers.UvicornWorker \
        --bind 0.0.0.0:${PORT:-8000} \
        --workers ${WEB_CONCURRENCY} \
        --timeout 120 \
        --graceful-timeout 30 \
        --keep-alive 30 \
        --max-requests 2000 \
        --max-requests-jitter 200 \
        --access-logfile -"]
