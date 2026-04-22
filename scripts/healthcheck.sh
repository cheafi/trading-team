#!/usr/bin/env bash
# healthcheck.sh — verify services are running after deploy
set -euo pipefail

cd /home/ubuntu/trading-team
PASS=true

echo "=== Service Health ==="

for svc in freqtrade agent-runner redis; do
  STATUS=$(docker compose ps --format '{{.State}}' "$svc" 2>/dev/null || echo "missing")
  if [[ "$STATUS" == "running" ]]; then
    echo "✅ $svc: running"
  else
    echo "❌ $svc: $STATUS"
    PASS=false
  fi
done

# Check freqtrade API responds
if curl -sf -o /dev/null -u "${FREQTRADE_USER:-freqtrader}:${FREQTRADE_PASS:-changeme}" \
  http://localhost:8080/api/v1/ping 2>/dev/null; then
  echo "✅ freqtrade API: responding"
else
  echo "⚠️  freqtrade API: not responding yet (may still be starting)"
fi

# Memory usage
echo ""
echo "=== Memory ==="
free -h | head -2

echo ""
echo "=== Container Resources ==="
docker stats --no-stream --format "table {{.Name}}\t{{.MemUsage}}\t{{.CPUPerc}}" 2>/dev/null || true

if [ "$PASS" = false ]; then
  echo ""
  echo "❌ Some services failed — check logs: docker compose logs"
  exit 1
fi
