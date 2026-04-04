#!/usr/bin/env bash
# ──────────────────────────────────────────────────
# Cheafi — Quick Start Script
# ──────────────────────────────────────────────────
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_DIR"


echo "� Cheafi Trading Team — Starting..."
echo "─────────────────────────────────"

# Create .env from example if missing
if [ ! -f .env ]; then
    echo "📝 Creating .env from .env.example..."
    cp .env.example .env
    echo "⚠️  Please edit .env with your API keys before running live!"
fi

# Create necessary data directories
mkdir -p freqtrade/user_data/{data,logs,backtest_results,notebooks}
mkdir -p shared

echo "🏗️  Building containers..."
docker compose build --parallel

echo "🚀 Starting services..."
docker compose up -d

echo ""
echo "─────────────────────────────────"
echo "✅ Services started!"
echo ""
echo "📊 Dashboard:    http://localhost:3000"
echo "🤖 Agent API:    http://localhost:3001"
echo "📈 Freqtrade:    http://localhost:8080"
echo ""
echo "📋 View logs:    docker compose logs -f"
echo "🛑 Stop:         docker compose down"
echo "─────────────────────────────────"
