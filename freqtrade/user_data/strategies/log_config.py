"""
Structured JSON Logging Configuration for CC Trading System
============================================================
Provides a JSON formatter for production logs that can be
ingested by Loki, ELK, or any JSON-aware log aggregator.

Usage in strategy:
    from log_config import configure_json_logging
    configure_json_logging()  # call once in bot_start()

The formatter enriches each log record with:
  - timestamp (ISO 8601)
  - level
  - component (strategy / ml_optimizer / regime_engine / etc.)
  - message
  - extra fields (pair, regime, side, etc.)
"""

import json
import logging
import sys
from datetime import datetime, timezone


class JSONFormatter(logging.Formatter):
    """
    Emit each log record as a single JSON line.
    Compatible with Loki, ELK, Datadog, etc.
    """

    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "component": record.name,
            "msg": record.getMessage(),
        }
        # Merge any extra fields passed via logger.info("...", extra={...})
        for key in ("pair", "regime", "side", "reason", "rate",
                     "profit", "edge_score", "funding_rate",
                     "trade_id", "duration_min", "exit_reason"):
            val = getattr(record, key, None)
            if val is not None:
                entry[key] = val
        # Include exception info if present
        if record.exc_info and record.exc_info[0]:
            entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(entry, default=str)


def configure_json_logging(level: str = "INFO") -> None:
    """
    Configure the root trading logger to emit structured JSON.
    Call once during bot_start() or module init.
    Only activates JSON format when TRADING_LOG_JSON=1 env var is set
    (to avoid breaking human-readable logs during development).
    """
    import os
    if os.environ.get("TRADING_LOG_JSON", "0") != "1":
        return  # keep default human-readable format

    root = logging.getLogger()
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JSONFormatter())
    # Replace existing handlers
    root.handlers = [handler]
    root.setLevel(getattr(logging, level.upper(), logging.INFO))


def get_structured_logger(name: str) -> logging.Logger:
    """
    Get a logger with the given component name.
    If JSON logging is configured, output will be JSON.
    Otherwise, standard Python logging format.
    """
    return logging.getLogger(name)
