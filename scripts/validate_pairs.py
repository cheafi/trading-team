#!/usr/bin/env python3
"""
Validate that all Freqtrade configs match the canonical pair universe.
Exit 0 if all match, exit 1 if any mismatch.

Usage:
  python scripts/validate_pairs.py
  # or inside Docker:
  docker compose exec freqtrade python /freqtrade/scripts/validate_pairs.py
"""
import json
import sys
from pathlib import Path

# Resolve paths relative to this script's location
REPO_ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = REPO_ROOT / "freqtrade" / "config"

# Fallback: if running inside Docker container
if not CONFIG_DIR.exists():
    CONFIG_DIR = Path("/freqtrade/config")

UNIVERSE_PATH = CONFIG_DIR / "pair_universe.json"

CONFIGS_TO_CHECK = [
    CONFIG_DIR / "config.json",
    CONFIG_DIR / "config_backtest.json",
]


def load_json(path):
    with open(path) as f:
        return json.load(f)


def main():
    if not UNIVERSE_PATH.exists():
        print(f"FAIL: pair_universe.json not found at {UNIVERSE_PATH}")
        return 1

    universe = load_json(UNIVERSE_PATH)
    canonical_pairs = sorted(universe["pairs"])
    canonical_blacklist = sorted(universe.get("pair_blacklist", []))
    version = universe.get("_version", "unknown")

    print(f"Pair universe v{version}: {len(canonical_pairs)} pairs")
    print(f"  {', '.join(p.split('/')[0] for p in canonical_pairs)}")

    errors = 0

    for cfg_path in CONFIGS_TO_CHECK:
        name = cfg_path.name
        if not cfg_path.exists():
            print(f"  SKIP: {name} not found")
            continue

        cfg = load_json(cfg_path)
        pairs = sorted(cfg.get("exchange", {}).get("pair_whitelist", []))
        blacklist = sorted(cfg.get("exchange", {}).get("pair_blacklist", []))

        # Check whitelist
        if pairs != canonical_pairs:
            missing = set(canonical_pairs) - set(pairs)
            extra = set(pairs) - set(canonical_pairs)
            print(f"  FAIL: {name} pair_whitelist mismatch")
            if missing:
                print(f"    Missing: {missing}")
            if extra:
                print(f"    Extra:   {extra}")
            errors += 1
        else:
            print(f"  OK:   {name} — {len(pairs)} pairs match")

        # Check blacklist (only for config.json which has it)
        if blacklist and blacklist != canonical_blacklist:
            print(f"  WARN: {name} pair_blacklist differs from universe")

    if errors:
        print(f"\n{errors} config(s) have pair mismatches!")
        return 1

    print("\nAll configs match the canonical pair universe.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
