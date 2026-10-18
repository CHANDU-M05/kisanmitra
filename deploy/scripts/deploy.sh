#!/usr/bin/env bash
# KisanMitra production deployment — zero-downtime rolling release with automatic rollback.
#
# Usage (on the server, normally invoked by the CD workflow):
#   IMAGE_PREFIX=ghcr.io/<owner>/kisanmitra RELEASE_TAG=<tag> [GHCR_USER=<user>] [SKIP_MIGRATIONS=true] \
#     bash deploy.sh deploy        # GHCR_USER triggers docker login; token is read from stdin
#   bash deploy.sh rollback        # return to the previously active release
#
# Important bash note: errexit (-e) is DISABLED inside functions called from
# an "if" condition. Every function that must propagate failure uses "|| return 1"
# explicitly instead of relying on set -e.
set -Eeuo pipefail

APP_ROOT="${APP_ROOT:-/opt/kisanmitra}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COMPOSE_FILE="${APP_ROOT}/deploy/docker-compose.production.yml"
APP_ENV_FILE="${APP_ROOT}/.env.production"
RELEASE_ENV_FILE="${APP_ROOT}/.release.env"
PREVIOUS_ENV_FILE="${APP_ROOT}/.release.env.previous"
LOCK_FILE="${APP_ROOT}/.deploy.lock"
HEALTH_TIMEOUT_SECONDS="${HEALTH_TIMEOUT_SECONDS:-180}"

log() { printf '[%s] %s\n' "$(date -u +%FT%TZ)" "$*"; }

compose() {
  # Compose interpolation precedence puts shell env vars ABOVE --env-file. The
  # rollback path restores .release.env while this process still exports the
  # failed release's IMAGE_PREFIX/RELEASE_TAG, so the files on disk must win:
  # read them explicitly and pass them as per-command overrides.
  local prefix tag
  prefix="$(read_env_value "${RELEASE_ENV_FILE}" IMAGE_PREFIX "${IMAGE_PREFIX:-}")"
  tag="$(read_env_value "${RELEASE_ENV_FILE}" RELEASE_TAG "${RELEASE_TAG:-}")"
  IMAGE_PREFIX="${prefix}" RELEASE_TAG="${tag}" \
    docker compose -p kisanmitra -f "${COMPOSE_FILE}" \
      --env-file "${APP_ENV_FILE}" --env-file "${RELEASE_ENV_FILE}" "$@"
}

read_env_value() {
  # Usage: read_env_value <file> <KEY> <default>
  local value
  value="$(grep -E "^${2}=" "$1" 2>/dev/null | tail -n1 | cut -d= -f2- || true)"
  printf '%s' "${value:-$3}"
}

wait_healthy() {
  local service="$1" deadline=$((SECONDS + HEALTH_TIMEOUT_SECONDS)) cid status
  log "Waiting for ${service} to become healthy (timeout ${HEALTH_TIMEOUT_SECONDS}s)..."
  while ((SECONDS < deadline)); do
    cid="$(compose ps -q "${service}" 2>/dev/null || true)"
    if [[ -n "${cid}" ]]; then
      status="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}nohealthcheck-{{.State.Status}}{{end}}' "${cid}" 2>/dev/null || true)"
      if [[ "${status}" == "healthy" || "${status}" == "nohealthcheck-running" ]]; then
        log "${service} is ${status}"
        return 0
      fi
    fi
    sleep 3
  done
  log "ERROR: ${service} did not become healthy within ${HEALTH_TIMEOUT_SECONDS}s"
  compose logs --tail 80 "${service}" || true
  return 1
}

run_migrations() {
  log "Running database schema initialisation (scripts/00_init_db.py)"
  # KisanMitra uses create_all, not Alembic. The lifespan handler also calls
  # this, but running it here before traffic is served makes the migration step
  # explicit and predictable regardless of worker startup ordering.
  compose run --rm --no-deps api-a python scripts/00_init_db.py || return 1
}

smoke_test() {
  local domain health_path attempt
  domain="$(read_env_value "${APP_ENV_FILE}" DOMAIN "")"
  health_path="$(read_env_value "${APP_ENV_FILE}" API_HEALTH_PATH "/health")"
  [[ -n "${domain}" ]] || { log "ERROR: DOMAIN is not set in ${APP_ENV_FILE}"; return 1; }
  log "Running local smoke test against https://${domain}/api${health_path}"
  for attempt in $(seq 1 20); do
    if curl -fsSk --max-time 5 --resolve "${domain}:443:127.0.0.1" "https://${domain}/api${health_path}" > /dev/null \
      && curl -fsSk --max-time 5 --resolve "${domain}:443:127.0.0.1" "https://${domain}/" > /dev/null; then
      log "Smoke test passed (attempt ${attempt})"
      return 0
    fi
    sleep 3
  done
  log "ERROR: Smoke test failed after all attempts"
  return 1
}

# Explicit "|| return 1" on every call: errexit is disabled inside functions
# called from an "if" context, so failures would otherwise be silently swallowed.
roll_out() {
  local skip_migrations="${1:-false}" service
  log "Starting data services..."
  compose up -d postgres redis n8n || return 1
  wait_healthy postgres || return 1
  wait_healthy redis || return 1

  if [[ "${skip_migrations}" != "true" ]]; then
    run_migrations || return 1
  else
    log "Skipping migrations (SKIP_MIGRATIONS=true — redeploying existing schema)"
  fi

  for service in api-a api-b; do
    log "Rolling ${service}..."
    compose up -d --no-deps --force-recreate "${service}" || return 1
    wait_healthy "${service}" || return 1
  done

  log "Updating edge (Caddy)..."
  compose up -d --no-deps --force-recreate edge || return 1
  wait_healthy edge || return 1

  smoke_test || return 1
}

rollback_release() {
  if [[ ! -f "${PREVIOUS_ENV_FILE}" ]]; then
    log "ERROR: No previous release recorded at ${PREVIOUS_ENV_FILE}; cannot roll back"
    return 1
  fi
  log "Rolling back to: $(grep -E '^RELEASE_TAG=' "${PREVIOUS_ENV_FILE}" || echo unknown)"
  cp -f "${PREVIOUS_ENV_FILE}" "${RELEASE_ENV_FILE}"
  # Pull the previous images (best-effort; they may still be present locally)
  compose pull api-a edge > /dev/null 2>&1 || true
  # Migrations are forward-only and are never re-run during a rollback.
  roll_out true || return 1
}

deploy_release() {
  : "${IMAGE_PREFIX:?IMAGE_PREFIX is required}"
  : "${RELEASE_TAG:?RELEASE_TAG is required}"

  if [[ -n "${GHCR_USER:-}" ]]; then
    log "Logging in to ghcr.io as ${GHCR_USER}"
    docker login ghcr.io -u "${GHCR_USER}" --password-stdin
  fi

  # Preserve the current release as a rollback target before overwriting
  if [[ -f "${RELEASE_ENV_FILE}" ]]; then
    cp -f "${RELEASE_ENV_FILE}" "${PREVIOUS_ENV_FILE}"
  fi

  cat > "${RELEASE_ENV_FILE}" <<EOF
IMAGE_PREFIX=${IMAGE_PREFIX}
RELEASE_TAG=${RELEASE_TAG}
EOF

  log "Deploying release ${RELEASE_TAG} from ${IMAGE_PREFIX}"
  # A pull failure must leave the release pointer matching what is actually
  # running, otherwise the next deploy would record a phantom rollback target.
  if ! compose pull api-a edge; then
    log "ERROR: images for release ${RELEASE_TAG} could not be pulled"
    if [[ -f "${PREVIOUS_ENV_FILE}" ]]; then
      cp -f "${PREVIOUS_ENV_FILE}" "${RELEASE_ENV_FILE}"
      log "Release pointer restored to the previously active release"
    else
      rm -f "${RELEASE_ENV_FILE}"
      log "No previous release recorded; release pointer removed (first deploy failed)"
    fi
    [[ -n "${GHCR_USER:-}" ]] && docker logout ghcr.io > /dev/null 2>&1 || true
    return 1
  fi

  if ! roll_out "${SKIP_MIGRATIONS:-false}"; then
    log "Release ${RELEASE_TAG} failed; attempting automatic rollback..."
    if rollback_release; then
      log "Rollback complete — previous release is live"
    else
      log "CRITICAL: Rollback failed. Manual intervention required."
    fi
    [[ -n "${GHCR_USER:-}" ]] && docker logout ghcr.io > /dev/null 2>&1 || true
    return 1
  fi

  # Prune images older than 7 days to reclaim disk space on the single host
  docker image prune -af --filter "until=168h" > /dev/null 2>&1 || true
  [[ -n "${GHCR_USER:-}" ]] && docker logout ghcr.io > /dev/null 2>&1 || true
  log "Release ${RELEASE_TAG} is live"
}

main() {
  local mode="${1:-deploy}"

  # Serialise deployments using an exclusive file lock on the host
  exec 9>"${LOCK_FILE}"
  flock -n 9 || { log "ERROR: Another deployment is already running (lock: ${LOCK_FILE})"; exit 1; }

  [[ -f "${APP_ENV_FILE}" ]] || { log "ERROR: Missing ${APP_ENV_FILE} — create it from deploy/env/production.env.example"; exit 1; }

  # Fail fast on a misconfigured host BEFORE any container is touched.
  local verify_script="${SCRIPT_DIR}/verify_environment.sh"
  [[ -f "${verify_script}" ]] || { log "ERROR: ${verify_script} missing — deploy scripts must stay together"; exit 1; }
  bash "${verify_script}" "${APP_ENV_FILE}" || { log "ERROR: environment validation failed — aborting before touching any container"; exit 1; }

  case "${mode}" in
    deploy)   deploy_release ;;
    rollback)
      [[ -f "${RELEASE_ENV_FILE}" ]] || { log "ERROR: No active release found at ${RELEASE_ENV_FILE}"; exit 1; }
      rollback_release
      ;;
    *)
      log "ERROR: Unknown mode '${mode}'. Usage: deploy.sh [deploy|rollback]"
      exit 2
      ;;
  esac
}

main "$@"
