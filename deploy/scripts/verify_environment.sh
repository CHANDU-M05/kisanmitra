#!/usr/bin/env bash
# KisanMitra — pre-deploy environment gate.
#
# Validates the server's .env.production BEFORE any container is touched, so a
# misconfigured host fails fast with clear messages instead of a half-applied
# release. Called by deploy.sh; can also be run manually:
#
#   bash verify_environment.sh [path/to/.env.production]
#   default: ${APP_ROOT:-/opt/kisanmitra}/.env.production
#
# Never prints secret VALUES — variable names only.
set -Eeuo pipefail

ENV_FILE="${1:-${APP_ROOT:-/opt/kisanmitra}/.env.production}"
failures=0

fail() { printf 'verify_environment: FAIL: %s\n' "$*" >&2; failures=$((failures + 1)); }
ok()   { printf 'verify_environment: ok: %s\n' "$*"; }

[[ -f "${ENV_FILE}" ]] || { printf 'verify_environment: FAIL: %s does not exist\n' "${ENV_FILE}" >&2; exit 1; }

mode="$(stat -c '%a' "${ENV_FILE}" 2>/dev/null || stat -f '%Lp' "${ENV_FILE}")"
if [[ "${mode}" != "600" && "${mode}" != "400" ]]; then
  fail "permissions are ${mode}; must be 600 (chmod 600 ${ENV_FILE})"
else
  ok "permissions ${mode}"
fi

get() { grep -E "^\s*${1}\s*=" "${ENV_FILE}" 2>/dev/null | tail -n1 | sed -E "s/^\s*${1}\s*=\s*//" || true; }

# Required to be PRESENT and NON-EMPTY. This mirrors what compose interpolation
# and backend/core/config.validate_production_settings demand; the backend
# remains the authority on strength (length/leak checks) at app startup.
REQUIRED_VARS=(
  APP_ENV DOMAIN ACME_EMAIL SECRET_KEY CORS_ORIGINS
  DB_HOST DB_PORT DB_NAME DB_USER DB_PASSWORD
  REDIS_PASSWORD N8N_ENCRYPTION_KEY
  WHATSAPP_VERIFY_TOKEN WHATSAPP_APP_SECRET
)
for var in "${REQUIRED_VARS[@]}"; do
  value="$(get "${var}")"
  if [[ -z "${value}" ]]; then
    fail "${var} is missing or empty"
  fi
done
[[ ${failures} -eq 0 ]] && ok "all ${#REQUIRED_VARS[@]} required variables present and non-empty"

# Placeholder detection: example values that must have been replaced.
for var in "${REQUIRED_VARS[@]}"; do
  value="$(get "${var}")"
  shopt -s nocasematch
  if [[ "${value}" == *"replace-with"* || "${value}" == *"changeme"* \
     || "${value}" == "your-"* || "${value}" == *"<"*" "* \
     || "${value}" == "TODO"* || "${value}" == "xxxx"* ]]; then
    fail "${var} still contains a placeholder value"
  fi
  shopt -u nocasematch
done
ok "no placeholder values detected"

[[ "$(get APP_ENV)" == "production" ]] || fail "APP_ENV must be exactly 'production' (got '$(get APP_ENV)')"

sk="$(get SECRET_KEY)"
if [[ -n "${sk}" && ${#sk} -lt 32 ]]; then
  fail "SECRET_KEY is ${#sk} characters; production requires at least 32"
fi

cors="$(get CORS_ORIGINS)"
if [[ "${cors}" == *"*"* ]]; then
  fail "CORS_ORIGINS contains a wildcard; list explicit trusted origins"
fi

domain="$(get DOMAIN)"
if [[ -n "${domain}" && "${domain}" != *.* && "${domain}" != "localhost" ]]; then
  fail "DOMAIN '${domain}' does not look like a public hostname"
fi

if [[ ${failures} -gt 0 ]]; then
  printf 'verify_environment: %d problem(s) in %s — fix them before deploying\n' "${failures}" "${ENV_FILE}" >&2
  exit 1
fi
ok "${ENV_FILE} passes pre-deploy validation"
