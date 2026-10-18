#!/usr/bin/env bash
# KisanMitra — generate fresh secrets for a production .env.production.
#
# Prints one "KEY=value" line per generated secret to STDOUT so the operator
# can paste them straight into the server's .env.production (created per
# docs/DEPLOYMENT_RUNBOOK.md). It NEVER writes into the repository and never
# logs values. Run over an encrypted channel (terminal on the SSH session);
# clear your shell history and scrollback afterwards if your policy requires it.
#
# Usage:
#   bash generate_secrets.sh            # stdout only (default)
#   bash generate_secrets.sh > /root/kisanmitra-secrets.txt && chmod 600 /root/kisanmitra-secrets.txt
#
# Third-party credentials cannot be generated here — rotate them at the
# provider and paste them in yourself (see the checklist printed at the end).
set -Eeuo pipefail

rand_hex() { openssl rand -hex "${1}"; }

# Values must satisfy backend validate_production_settings:
# SECRET_KEY >= 32 chars and not a previously leaked key (64 hex chars here).
printf 'SECRET_KEY=%s\n'              "$(rand_hex 32)"
printf 'DB_PASSWORD=%s\n'             "$(rand_hex 16)"
printf 'REDIS_PASSWORD=%s\n'          "$(rand_hex 16)"
printf 'N8N_ENCRYPTION_KEY=%s\n'      "$(rand_hex 16)"
printf 'WHATSAPP_VERIFY_TOKEN=%s\n'   "$(rand_hex 8)"

cat >&2 <<'EOF'
--- Now rotate/set these at their PROVIDERS (never reuse an old value) ---
  WHATSAPP_TOKEN            Meta Business / WhatsApp Cloud API  (permanent token)
  WHATSAPP_APP_SECRET       Meta app dashboard (required: webhook HMAC verify)
  WHATSAPP_PHONE_NUMBER_ID  Cloud API setup page
  GEMINI_API_KEY            Google AI Studio                     (optional)
  DATA_GOV_API_KEY        data.gov.in                            (optional)
  TELEGRAM_BOT_TOKEN / TELEGRAM_WEBHOOK_SECRET                   @BotFather
If any previous SECRET_KEY / DB_PASSWORD / token was ever committed, leaked in
a diff, or pasted into a chat, treat it as burned and issue a NEW value.
EOF
