#!/usr/bin/env bash
# ============================================================
# KisanMitra — Arch Linux Setup Script (Improved 2026 Version)
# Run as normal user: bash setup_kisanmitra.sh
# ============================================================

set -euo pipefail

echo "======================================"
echo " KisanMitra Arch Linux Setup (Fixed)"
echo "======================================"

msg() { echo -e "\n[INFO] $1"; }
err() { echo -e "\n[ERROR] $1" >&2; exit 1; }

PROJECT_DIR="$HOME/kisanmitra"
cd "$PROJECT_DIR" || err "Cannot cd into $PROJECT_DIR"

msg "[1/9] Updating system..."
sudo pacman -Syu --noconfirm || err "pacman -Syu failed"

msg "[2/9] Installing dependencies..."
sudo pacman -S --needed --noconfirm \
    python python-pip python-virtualenv \
    postgresql postgis \
    git curl wget base-devel \
    nodejs npm \
    docker docker-compose \
    redis htop jq \
    python-psycopg2 python-sqlalchemy \
    || err "Core packages failed"

msg "[3/9] Installing/updating yay..."
if ! command -v yay &>/dev/null; then
    git clone https://aur.archlinux.org/yay.git /tmp/yay
    cd /tmp/yay
    makepkg -si --noconfirm || err "yay installation failed"
    cd - || err "cd back failed"
    rm -rf /tmp/yay
else
    yay -Syu --noconfirm yay || true
fi

msg "[4/9] Setting up PostgreSQL..."
PG_DATA="/var/lib/postgres/data"

if [ ! -d "$PG_DATA" ] || [ -z "$(ls -A "$PG_DATA")" ]; then
    msg "Initializing PostgreSQL cluster..."
    sudo mkdir -p "$PG_DATA"
    sudo chown -R postgres:postgres "$PG_DATA"
    sudo -u postgres initdb -D "$PG_DATA" || err "initdb failed — check locale"
fi

sudo systemctl enable --now postgresql || err "PostgreSQL service failed"

# Create user & DB (idempotent)
sudo -u postgres psql -c "SELECT 1 FROM pg_roles WHERE rolname='kisanmitra_user'" | grep -q 1 || \
    sudo -u postgres createuser kisanmitra_user
sudo -u postgres psql -c "ALTER USER kisanmitra_user WITH ENCRYPTED PASSWORD 'your_secure_password';" || true
sudo -u postgres createdb -O kisanmitra_user kisanmitra || true
sudo -u postgres psql -d kisanmitra -c "CREATE EXTENSION IF NOT EXISTS postgis;" || true

msg "[5/9] Redis..."
sudo systemctl enable --now redis || err "Redis failed"

msg "[6/9] Docker..."
sudo systemctl enable --now docker || err "Docker failed"
if ! groups | grep -q docker; then
    sudo usermod -aG docker "$USER"
    msg "Added to docker group — LOG OUT AND BACK IN AFTER SETUP!"
fi

msg "[7/9] Python venv..."
VENV="$PROJECT_DIR/venv"
[ -d "$VENV" ] || python -m venv --prompt kisanmitra "$VENV"
source "$VENV/bin/activate"

pip install --upgrade pip wheel setuptools || err "pip upgrade failed"

pip install \
    pandas numpy scikit-learn matplotlib seaborn requests beautifulsoup4 lxml \
    psycopg2-binary sqlalchemy fastapi uvicorn python-dotenv joblib httpx \
    pydantic python-multipart geopandas shapely pyproj openpyxl schedule \
    redis celery[redis] pytest black ipython flower \
    || err "pip install failed"

deactivate
msg "Python packages installed."

msg "[8/9] Creating .env template (if missing)..."
ENV_FILE="$PROJECT_DIR/.env"
if [ ! -f "$ENV_FILE" ]; then
    cat > "$ENV_FILE" << 'EOF'
# DATABASE
DB_HOST=localhost
DB_PORT=5432
DB_NAME=kisanmitra
DB_USER=kisanmitra_user
DB_PASSWORD=your_secure_password

# REDIS
REDIS_URL=redis://localhost:6379/0

# OPENAI / WhatsApp / APIs
OPENAI_API_KEY=sk-...
WHATSAPP_TOKEN=...
WHATSAPP_PHONE_NUMBER_ID=...
WHATSAPP_VERIFY_TOKEN=kisanmitra_verify_2025
DATA_GOV_API_KEY=...

# APP
APP_ENV=development
APP_PORT=8000
SECRET_KEY=$(openssl rand -hex 32)
EOF
    chmod 600 "$ENV_FILE"
else
    msg ".env already exists — skipping."
fi

echo ""
echo "======================================"
echo " SETUP COMPLETE!"
echo "======================================"
echo "NEXT:"
echo "1. LOG OUT AND BACK IN (for docker group)"
echo "2. Edit .env: nano ~/kisanmitra/.env"
echo "3. Activate venv: cd ~/kisanmitra && source venv/bin/activate"
echo "4. Run your first script (when ready)"
echo ""
echo "Check services: systemctl status postgresql redis docker"
