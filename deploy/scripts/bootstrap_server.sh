#!/usr/bin/env bash
# KisanMitra one-time server bootstrap script.
# Run ONCE as root (or via sudo) on a freshly provisioned Oracle Cloud Always Free Ubuntu 22.04/24.04 ARM VM.
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/<owner>/kisanmitra/main/deploy/scripts/bootstrap_server.sh | sudo bash
#   # or after uploading:
#   sudo bash /tmp/bootstrap_server.sh
#
# After completion, the 'deploy' user has Docker access and the CI public key
# in authorized_keys. The application is then deployed via the CD workflow.
set -Eeuo pipefail

DEPLOY_USER="deploy"
APP_ROOT="/opt/kisanmitra"
LOG_FILE="/var/log/kisanmitra-bootstrap.log"

log() { printf '[%s] %s\n' "$(date -u +%FT%TZ)" "$*" | tee -a "${LOG_FILE}"; }
die() { log "FATAL: $*"; exit 1; }

[[ "$(id -u)" -eq 0 ]] || die "This script must be run as root"

# ── 1. System packages ─────────────────────────────────────────────────────────
log "Updating package index and installing prerequisites..."
export DEBIAN_FRONTEND=noninteractive
apt-get update -q
apt-get install -yq \
    ca-certificates \
    curl \
    gnupg \
    lsb-release \
    ufw \
    fail2ban \
    unattended-upgrades \
    apt-transport-https \
    rsync \
    htop \
    jq \
    net-tools \
    postgresql-client

# ── 2. Docker (official repository) ───────────────────────────────────────────
log "Installing Docker..."
if ! command -v docker &> /dev/null; then
    install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
        | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
    chmod a+r /etc/apt/keyrings/docker.gpg
    printf 'deb [arch=%s signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu %s stable\n' \
        "$(dpkg --print-architecture)" \
        "$(lsb_release -cs)" \
        > /etc/apt/sources.list.d/docker.list
    apt-get update -q
    apt-get install -yq docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
    systemctl enable --now docker
    log "Docker installed: $(docker --version)"
else
    log "Docker already installed: $(docker --version)"
fi

# ── 3. Deploy user ────────────────────────────────────────────────────────────
log "Creating deploy user '${DEPLOY_USER}'..."
if ! id "${DEPLOY_USER}" &>/dev/null; then
    useradd --system --create-home --shell /bin/bash "${DEPLOY_USER}"
fi
usermod -aG docker "${DEPLOY_USER}"
log "User '${DEPLOY_USER}' has Docker access"

# ── 4. SSH authorized key for the CI/CD workflow ──────────────────────────────
# Paste the public key from your PRODUCTION_SSH_KEY pair here, or set the
# DEPLOY_PUBLIC_KEY environment variable before running this script.
# Example: DEPLOY_PUBLIC_KEY="ssh-ed25519 AAAA... ci@kisanmitra" bash bootstrap_server.sh
DEPLOY_SSH_DIR="/home/${DEPLOY_USER}/.ssh"
install -o "${DEPLOY_USER}" -g "${DEPLOY_USER}" -m 700 -d "${DEPLOY_SSH_DIR}"
if [[ -n "${DEPLOY_PUBLIC_KEY:-}" ]]; then
    printf '%s\n' "${DEPLOY_PUBLIC_KEY}" >> "${DEPLOY_SSH_DIR}/authorized_keys"
    chmod 600 "${DEPLOY_SSH_DIR}/authorized_keys"
    chown "${DEPLOY_USER}:${DEPLOY_USER}" "${DEPLOY_SSH_DIR}/authorized_keys"
    log "CI public key written to ${DEPLOY_SSH_DIR}/authorized_keys"
else
    log "WARNING: DEPLOY_PUBLIC_KEY not set. Add the CI public key manually:"
    log "  echo 'ssh-ed25519 AAAA...' >> ${DEPLOY_SSH_DIR}/authorized_keys"
fi

# ── 5. Application directories ────────────────────────────────────────────────
log "Creating application directories under ${APP_ROOT}..."
mkdir -p \
    "${APP_ROOT}/deploy/scripts" \
    "${APP_ROOT}/deploy/caddy" \
    "${APP_ROOT}/backups"
chown -R "${DEPLOY_USER}:${DEPLOY_USER}" "${APP_ROOT}"
chmod 750 "${APP_ROOT}"
log "Directories created"

# ── 6. Docker daemon log rotation ─────────────────────────────────────────────
log "Configuring Docker daemon log rotation..."
cat > /etc/docker/daemon.json <<'EOF'
{
  "log-driver": "json-file",
  "log-opts": {
    "max-size": "10m",
    "max-file": "3"
  }
}
EOF
systemctl reload docker
log "Docker log rotation configured"

# ── 7. Swap (4 GB) ────────────────────────────────────────────────────────────
if ! swapon --show | grep -q '/swapfile'; then
    log "Creating 4 GB swap file..."
    fallocate -l 4G /swapfile
    chmod 600 /swapfile
    mkswap /swapfile
    swapon /swapfile
    echo '/swapfile none swap sw 0 0' >> /etc/fstab
    log "Swap enabled"
else
    log "Swap already configured"
fi

# ── 8. Kernel tuning (sysctl) ─────────────────────────────────────────────────
log "Applying kernel tuning..."
cat > /etc/sysctl.d/99-kisanmitra.conf <<'EOF'
# Increase OS socket backlog for high-concurrency API
net.core.somaxconn = 65535
net.core.netdev_max_backlog = 4096
net.ipv4.tcp_max_syn_backlog = 8192
# Reduce swap aggressiveness (prefer RAM)
vm.swappiness = 10
# Caddy / HTTP/3 needs larger UDP buffers
net.core.rmem_max = 7500000
net.core.wmem_max = 7500000
EOF
sysctl --system > /dev/null
log "Kernel tuning applied"

# ── 9. Host firewall (ufw) ────────────────────────────────────────────────────
log "Configuring host firewall..."
ufw default deny incoming
ufw default allow outgoing
ufw allow ssh
ufw allow 80/tcp
ufw allow 443/tcp
ufw allow 443/udp   # HTTP/3 (QUIC)
ufw --force enable
log "Firewall rules active"

# ── 10. fail2ban ──────────────────────────────────────────────────────────────
log "Enabling fail2ban..."
systemctl enable --now fail2ban
log "fail2ban running"

# ── 11. Unattended security upgrades ─────────────────────────────────────────
log "Configuring unattended security upgrades..."
dpkg-reconfigure -plow unattended-upgrades
log "Unattended upgrades configured"

# ── 12. Nightly PostgreSQL backup cron ────────────────────────────────────────
log "Installing nightly backup cron job (21:00 UTC)..."
BACKUP_SCRIPT="${APP_ROOT}/deploy/scripts/backup_postgres.sh"
CRON_LINE="0 21 * * * ${DEPLOY_USER} bash ${BACKUP_SCRIPT} >> /var/log/kisanmitra-backup.log 2>&1"
if ! grep -qF "${BACKUP_SCRIPT}" /etc/cron.d/kisanmitra-backup 2>/dev/null; then
    printf '%s\n' "${CRON_LINE}" > /etc/cron.d/kisanmitra-backup
    chmod 644 /etc/cron.d/kisanmitra-backup
    log "Backup cron installed: ${CRON_LINE}"
else
    log "Backup cron already present"
fi

# ── Done ──────────────────────────────────────────────────────────────────────
log "Bootstrap complete."
log ""
log "Next steps:"
log "  1. Add the CI public key to ${DEPLOY_SSH_DIR}/authorized_keys (if not set via DEPLOY_PUBLIC_KEY)"
log "  2. Copy deploy/env/production.env.example to ${APP_ROOT}/.env.production and fill in all values"
log "  3. Point your DNS A record to this server's public IP"
log "  4. Run the GitHub Actions CD workflow to deploy the application"
log ""
log "Server public IP: $(curl -4 -fsS --max-time 5 https://ifconfig.me || echo 'unknown')"
