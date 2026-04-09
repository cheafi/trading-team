"""
Model Registry — version tracking, metadata, rollback for ML artifacts.

Every training run produces a version that captures:
  - Snapshot of all model artifacts (params, models, configs)
  - Training metadata (timestamp, trade count, feature hash)
  - OOS metrics from walk-forward validation
  - Drift status vs previous version

Usage:
  from model_registry import ModelRegistry
  registry = ModelRegistry(MODEL_DIR)
  version_id = registry.register(metadata)  # after training
  registry.rollback(version_id)              # restore a version
  registry.list_versions()                   # show all versions
"""

import hashlib
import json
import os
import shutil
from datetime import datetime
from pathlib import Path


class ModelRegistry:
    """Track and manage ML model versions."""

    # Files that constitute a complete model snapshot
    ARTIFACT_FILES = [
        "best_params.json",
        "quality_model.pkl",
        "discipline_params.json",
        "anti_patterns.json",
    ]

    # Files that are informational (not restored on rollback)
    INFO_FILES = [
        "training_log.json",
        "performance_history.json",
        "regime_model.pkl",  # trained but unused
    ]

    def __init__(self, model_dir=None):
        self.model_dir = Path(
            model_dir or os.getenv("MODEL_DIR", "/freqtrade/user_data/ml_models")
        )
        self.versions_dir = self.model_dir / "versions"
        self.registry_path = self.model_dir / "registry.json"
        self.versions_dir.mkdir(parents=True, exist_ok=True)

    def _load_registry(self):
        """Load or initialize the registry."""
        if self.registry_path.exists():
            try:
                with open(self.registry_path) as f:
                    return json.load(f)
            except Exception:
                pass
        return {"active": None, "versions": []}

    def _save_registry(self, registry):
        """Atomic write of registry file."""
        tmp = self.registry_path.with_suffix(".tmp")
        with open(tmp, "w") as f:
            json.dump(registry, f, indent=2)
        tmp.rename(self.registry_path)

    def _compute_params_hash(self):
        """SHA-256 hash of best_params.json for drift detection."""
        params_path = self.model_dir / "best_params.json"
        if not params_path.exists():
            return None
        content = params_path.read_bytes()
        return hashlib.sha256(content).hexdigest()[:12]

    def _extract_oos_metrics(self):
        """Extract OOS metrics from the most recent training log entry."""
        log_path = self.model_dir / "training_log.json"
        if not log_path.exists():
            return {}
        try:
            with open(log_path) as f:
                log = json.load(f)
            if not log:
                return {}
            latest = log[-1]
            scores = latest.get("strategy_scores", {})
            # Aggregate OOS summary
            total_trades = 0
            weighted_wr = 0
            for s, sc in scores.items():
                n = sc.get("trade_count", 0)
                total_trades += n
                weighted_wr += sc.get("win_rate", 0) * n
            avg_wr = weighted_wr / total_trades if total_trades else 0
            return {
                "total_trades": total_trades,
                "avg_win_rate": round(avg_wr, 4),
                "strategies_scored": len(scores),
            }
        except Exception:
            return {}

    def register(self, extra_metadata=None):
        """
        Register the current model artifacts as a new version.
        Called after a successful training run.

        Returns: version_id string
        """
        now = datetime.utcnow()
        version_id = now.strftime("%Y%m%dT%H%M%S")
        version_dir = self.versions_dir / version_id
        version_dir.mkdir(parents=True, exist_ok=True)

        # Snapshot all artifact files
        artifacts_saved = []
        for fname in self.ARTIFACT_FILES:
            src = self.model_dir / fname
            if src.exists():
                shutil.copy2(src, version_dir / fname)
                artifacts_saved.append(fname)

        if not artifacts_saved:
            # Nothing to register
            shutil.rmtree(version_dir, ignore_errors=True)
            return None

        # Build version metadata
        params_hash = self._compute_params_hash()
        oos_metrics = self._extract_oos_metrics()

        registry = self._load_registry()
        prev_active = registry.get("active")

        # Detect drift from previous version
        drift = None
        if prev_active:
            prev_entry = next(
                (v for v in registry["versions"] if v["version_id"] == prev_active),
                None,
            )
            if prev_entry and prev_entry.get("params_hash"):
                if prev_entry["params_hash"] != params_hash:
                    drift = {
                        "from_version": prev_active,
                        "params_changed": True,
                        "prev_hash": prev_entry["params_hash"],
                        "new_hash": params_hash,
                    }

        version_entry = {
            "version_id": version_id,
            "timestamp": now.isoformat() + "Z",
            "params_hash": params_hash,
            "artifacts": artifacts_saved,
            "oos_metrics": oos_metrics,
            "drift": drift,
            **(extra_metadata or {}),
        }

        registry["versions"].append(version_entry)
        registry["active"] = version_id

        # Keep last 20 versions on disk, prune older
        max_versions = 20
        if len(registry["versions"]) > max_versions:
            to_prune = registry["versions"][:-max_versions]
            registry["versions"] = registry["versions"][-max_versions:]
            for old in to_prune:
                old_dir = self.versions_dir / old["version_id"]
                if old_dir.exists():
                    shutil.rmtree(old_dir, ignore_errors=True)

        self._save_registry(registry)
        return version_id

    def rollback(self, version_id):
        """
        Restore model artifacts from a previous version.
        Returns True on success.
        """
        version_dir = self.versions_dir / version_id
        if not version_dir.exists():
            raise FileNotFoundError(
                f"Version {version_id} not found in {self.versions_dir}"
            )

        restored = []
        for fname in self.ARTIFACT_FILES:
            src = version_dir / fname
            if src.exists():
                dst = self.model_dir / fname
                shutil.copy2(src, dst)
                restored.append(fname)

        # Update registry active pointer
        registry = self._load_registry()
        registry["active"] = version_id
        # Add rollback marker
        registry.setdefault("rollback_history", []).append(
            {
                "rolled_back_to": version_id,
                "timestamp": datetime.utcnow().isoformat() + "Z",
                "restored_files": restored,
            }
        )
        self._save_registry(registry)
        return True

    def list_versions(self):
        """Return list of all registered versions."""
        registry = self._load_registry()
        return {
            "active": registry.get("active"),
            "versions": registry.get("versions", []),
        }

    def get_active(self):
        """Return metadata for the currently active version."""
        registry = self._load_registry()
        active_id = registry.get("active")
        if not active_id:
            return None
        return next(
            (v for v in registry.get("versions", []) if v["version_id"] == active_id),
            None,
        )

    def check_drift(self):
        """
        Compare current on-disk artifacts against the active version.
        Returns drift info if params have changed since last registration.
        """
        active = self.get_active()
        if not active:
            return {"status": "no_registry", "drifted": False}
        current_hash = self._compute_params_hash()
        registered_hash = active.get("params_hash")
        drifted = current_hash != registered_hash
        return {
            "status": "drifted" if drifted else "clean",
            "drifted": drifted,
            "active_version": active["version_id"],
            "active_hash": registered_hash,
            "current_hash": current_hash,
            "active_since": active.get("timestamp"),
        }
