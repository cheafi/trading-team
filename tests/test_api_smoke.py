"""
Smoke tests for agent-runner HTTP API.

These tests require the agent-runner to be running on localhost:3001.
Run: python -m pytest tests/test_api_smoke.py -v

For CI, skip with: pytest -m "not integration"
"""

import json

import pytest
import requests

BASE_URL = "http://localhost:3001"
TIMEOUT = 10


def api_available():
    """Check if agent-runner is reachable."""
    try:
        r = requests.get(f"{BASE_URL}/health", timeout=3)
        return r.status_code == 200
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not api_available(),
    reason="Agent-runner not available at localhost:3001",
)


class TestHealthEndpoints:
    """Basic health and status endpoints."""

    def test_health(self):
        r = requests.get(f"{BASE_URL}/health", timeout=TIMEOUT)
        assert r.status_code == 200
        data = r.json()
        assert data.get("status") == "ok"

    def test_agents_list(self):
        r = requests.get(f"{BASE_URL}/api/agents", timeout=TIMEOUT)
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, list)
        assert len(data) >= 7, "Expected at least 7 agents"
        # Each agent should have required fields
        for agent in data:
            assert "id" in agent
            assert "name" in agent
            assert "status" in agent

    def test_findings(self):
        r = requests.get(f"{BASE_URL}/api/findings", timeout=TIMEOUT)
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, list)


class TestTradingEndpoints:
    """Endpoints that proxy to Freqtrade."""

    def test_profit(self):
        r = requests.get(f"{BASE_URL}/api/profit", timeout=TIMEOUT)
        # May return 200 with data or 502 if FT is down
        assert r.status_code in (200, 502)

    def test_trades(self):
        r = requests.get(f"{BASE_URL}/api/trades", timeout=TIMEOUT)
        assert r.status_code in (200, 502)

    def test_status(self):
        r = requests.get(f"{BASE_URL}/api/status", timeout=TIMEOUT)
        assert r.status_code in (200, 502)


class TestMLEndpoints:
    """ML model and quality gate endpoints."""

    def test_ml_status(self):
        r = requests.get(f"{BASE_URL}/api/ml/status", timeout=TIMEOUT)
        assert r.status_code == 200
        data = r.json()
        # Should have model info
        assert isinstance(data, dict)

    def test_rejection_journal(self):
        r = requests.get(f"{BASE_URL}/api/rejections", timeout=TIMEOUT)
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, list)


class TestKillSwitch:
    """Kill switch must be readable (not toggled in test)."""

    def test_kill_switch_status(self):
        r = requests.get(f"{BASE_URL}/api/kill-switch", timeout=TIMEOUT)
        assert r.status_code == 200
        data = r.json()
        assert "active" in data


class TestBenchmark:
    """Benchmark centre endpoint."""

    def test_benchmark_returns_data(self):
        r = requests.get(f"{BASE_URL}/api/benchmark", timeout=TIMEOUT)
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, dict)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
