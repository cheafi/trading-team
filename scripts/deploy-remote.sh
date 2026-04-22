#!/usr/bin/env bash
# deploy-remote.sh — runs ON the OCI instance after rsync
set -euo pipefail

DEPLOY_DIR="/home/ubuntu/trading-team"
cd "$DEPLOY_DIR"

# ── First-time: add 2GB swap (1GB RAM micro instance) ──
if [ ! -f /swapfile ]; then
  echo "=== Creating 2GB swap ==="
  sudo fallocate -l 2G /swapfile
  sudo chmod 600 /swapfile
  sudo mkswap /swapfile
  sudo swapon /swapfile
  echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
fi

# ── First-time: install Docker ──
if ! command -v docker &>/dev/null; then
  echo "=== Installing Docker ==="
  sudo apt-get update -qq
  sudo apt-get install -y -qq docker.io docker-compose-plugin
  sudo usermod -aG docker ubuntu
  sudo systemctl enable docker
  sudo systemctl start docker
  echo "Docker installed — re-run deploy (group membership needs re-login)"
  exit 0
fi

# ── Ensure shared/ exists (Dockerfile.agents COPY needs it) ──
mkdir -p shared

# ── Create .env if missing (dry_run=true by default) ──
if [ ! -f .env ]; then
  cat > .env <<'ENVEOF'
FREQTRADE_USER=freqtrader
FREQTRADE_PASS=changeme
REDIS_PASSWORD=changeme
DRY_RUN=true
ALLOW_OPEN_AUTH=false
ENVEOF
  echo "Created default .env — edit secrets before going live!"
fi

# OCI Micro (1GB RAM) — skip dashboard, limit memory
export COMPOSE_PROFILES=core

# Stop old containers gracefully
docker compose down --timeout 30 2>/dev/null || true

# Prune to save disk on micro instance
docker image prune -f 2>/dev/null || true

# Build and start (no dashboard — saves ~400MB RAM)
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build --remove-orphans

echo "=== Deploy complete ==="
docker compose ps
