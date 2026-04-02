#!/usr/bin/env bash
# Stop all trading team services
set -euo pipefail
cd "$(dirname "$0")/.."
export PATH="/Applications/Docker.app/Contents/Resources/bin:$PATH"

echo "🛑 Stopping DanDan Trading Team..."
docker compose down
echo "✅ All services stopped."
