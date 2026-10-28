#!/usr/bin/env bash
# KisanMitra nightly PostgreSQL backup.
# Invoked by /etc/cron.d/kisanmitra-backup at 21:00 UTC as the deploy user.
#
# Produces a custom-format pg_dump, verifies it is non-empty, atomically renames
# it into place, prunes retention window, and optionally copies offsite via rclone.
#
# Required environment (sourced from .env.production or exported by the cron environment):
#   DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD
#
# Optional:
#   BACKUP_DIR       (default: /opt/kisanmitra/backups)
#   BACKUP_RETAIN    (days, default: 14)
#   RCLONE_REMOTE    (e.g. "remote:kisanmitra-backups" — leave unset to skip offsite copy)
set -Eeuo pipefail

APP_ROOT="/opt/kisanmitra"
ENV_FILE="${APP_ROOT}/.env.production"
BACKUP_DIR="${BACKUP_DIR:-${APP_ROOT}/backups}"
BACKUP_RETAIN="${BACKUP_RETAIN:-14}"

log() { printf '[%s] %s\n' "$(date -u +%FT%TZ)" "$*"; }

# Source .env.production to get DB credentials if not already in environment
if [[ -z "${DB_PASSWORD:-}" && -f "${ENV_FILE}" ]]; then
    # Only export the DB_ variables to avoid leaking WHATSAPP/GEMINI tokens into logs
    set -a
    # shellcheck disable=SC1090
    eval "$(grep -E '^(DB_HOST|DB_PORT|DB_NAME|DB_USER|DB_PASSWORD)=' "${ENV_FILE}")"
    set +a
fi

: "${DB_HOST:?DB_HOST is required}"
: "${DB_PORT:?DB_PORT is required}"
: "${DB_NAME:?DB_NAME is required}"
: "${DB_USER:?DB_USER is required}"
: "${DB_PASSWORD:?DB_PASSWORD is required}"

mkdir -p "${BACKUP_DIR}"

TIMESTAMP="$(date -u +%Y%m%d-%H%M%S)"
DUMP_TMP="${BACKUP_DIR}/.kisanmitra-${TIMESTAMP}.dump.tmp"
DUMP_FINAL="${BACKUP_DIR}/kisanmitra-${TIMESTAMP}.dump"

log "Starting backup: ${DB_NAME}@${DB_HOST}:${DB_PORT} → ${DUMP_FINAL}"

# pg_dump inside the postgres container for reliability; falls back to host pg_dump
if docker exec kisanmitra-postgres pg_dump \
    --username="${DB_USER}" \
    --format=custom \
    --no-password \
    "${DB_NAME}" \
    > "${DUMP_TMP}" 2>/dev/null; then
    log "Backup produced via container pg_dump"
else
    log "Container pg_dump not available; falling back to host pg_dump"
    PGPASSWORD="${DB_PASSWORD}" pg_dump \
        --host="${DB_HOST}" \
        --port="${DB_PORT}" \
        --username="${DB_USER}" \
        --format=custom \
        "${DB_NAME}" \
        > "${DUMP_TMP}"
fi

# Verify the dump is non-empty (a zero-byte file means pg_dump failed silently)
DUMP_SIZE="$(stat -c%s "${DUMP_TMP}" 2>/dev/null || echo 0)"
if [[ "${DUMP_SIZE}" -lt 1024 ]]; then
    log "ERROR: Dump file is suspiciously small (${DUMP_SIZE} bytes); aborting"
    rm -f "${DUMP_TMP}"
    exit 1
fi

# Atomic rename so readers never see a partial file
mv -f "${DUMP_TMP}" "${DUMP_FINAL}"
log "Backup complete: ${DUMP_FINAL} ($(numfmt --to=iec "${DUMP_SIZE}"))"

# ── Retention pruning ─────────────────────────────────────────────────────────
log "Pruning backups older than ${BACKUP_RETAIN} days..."
find "${BACKUP_DIR}" -maxdepth 1 -name "kisanmitra-*.dump" -mtime "+${BACKUP_RETAIN}" -print -delete
log "Retention pruning complete"

# ── Optional offsite copy via rclone ─────────────────────────────────────────
if [[ -n "${RCLONE_REMOTE:-}" ]]; then
    log "Copying to offsite: ${RCLONE_REMOTE}"
    if command -v rclone &>/dev/null; then
        rclone copy "${DUMP_FINAL}" "${RCLONE_REMOTE}/" \
            --log-level INFO \
            --log-file /var/log/kisanmitra-rclone.log \
            || log "WARNING: rclone copy failed (local backup is still intact)"
        log "Offsite copy complete"
    else
        log "WARNING: rclone not installed; skipping offsite copy"
    fi
fi

log "Backup finished successfully"
