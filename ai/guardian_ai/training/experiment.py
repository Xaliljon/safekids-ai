"""Experiment tracking: no anonymous models, ever.

Every training run gets an isolated directory and an ``experiment.json``
that ties the artifact back to everything that produced it: dataset and
taxonomy versions, git commit, full config, timings, metrics and the
model checksum. A model without this record does not exist as far as the
promotion pipeline is concerned.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from guardian_ai.training.config import TrainingConfig
from guardian_ai.training.errors import ExperimentError

EXPERIMENT_FILE = "experiment.json"
REPORTS_DIR = "reports"
CHECKPOINTS_DIR = "checkpoints"
EXPORT_DIR = "export"


def git_commit(repo_hint: Path | None = None) -> str:
    """Current commit hash, or 'unknown' outside a checkout — recorded
    either way so the record never lies by omission."""
    try:
        result = subprocess.run(  # noqa: S603 - fixed argv, no user input
            ["git", "rev-parse", "HEAD"],  # noqa: S607
            capture_output=True,
            text=True,
            timeout=5,
            cwd=str(repo_hint) if repo_hint else None,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return "unknown"
    return result.stdout.strip() if result.returncode == 0 else "unknown"


def _now() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


@dataclass(slots=True)
class Experiment:
    """One isolated training run and its permanent record."""

    run_dir: Path
    record: dict[str, Any]

    # ------------------------------------------------------------ creation

    @staticmethod
    def create(
        config: TrainingConfig,
        dataset_name: str,
        dataset_version: str,
        taxonomy_name: str,
        taxonomy_version: str,
    ) -> Experiment:
        experiment_id = f"{_now()[:19].replace(':', '')}-{config.name}-{uuid4().hex[:6]}"
        run_dir = config.output_dir / experiment_id
        if run_dir.exists():
            raise ExperimentError(f"run directory already exists: {run_dir}")
        run_dir.mkdir(parents=True)
        (run_dir / REPORTS_DIR).mkdir()
        (run_dir / CHECKPOINTS_DIR).mkdir()
        (run_dir / EXPORT_DIR).mkdir()
        record: dict[str, Any] = {
            "experiment_id": experiment_id,
            "status": "created",
            "config": config.to_dict(),
            "dataset": {"name": dataset_name, "version": dataset_version},
            "taxonomy": {"name": taxonomy_name, "version": taxonomy_version},
            "git_commit": git_commit(),
            "started_utc": None,
            "finished_utc": None,
            "epochs_completed": 0,
            "metrics": {},
            "checksums": {},
            "promotion": None,
        }
        experiment = Experiment(run_dir=run_dir, record=record)
        experiment.save()
        return experiment

    @staticmethod
    def load(run_dir: Path) -> Experiment:
        path = run_dir / EXPERIMENT_FILE
        if not path.is_file():
            raise ExperimentError(f"no experiment record at {path}")
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ExperimentError(f"corrupt experiment record at {path}: {exc}") from exc
        return Experiment(run_dir=run_dir, record=record)

    # ------------------------------------------------------------ lifecycle

    def start(self) -> None:
        self.record["status"] = "training"
        if self.record["started_utc"] is None:
            self.record["started_utc"] = _now()
        self.save()

    def finish(self, status: str = "completed") -> None:
        self.record["status"] = status
        self.record["finished_utc"] = _now()
        self.save()

    def update(self, **fields: Any) -> None:
        self.record.update(fields)
        self.save()

    def set_metrics(self, metrics: dict[str, Any]) -> None:
        self.record["metrics"] = metrics
        self.save()

    def set_checksum(self, artifact: str, sha256: str) -> None:
        self.record["checksums"][artifact] = sha256
        self.save()

    def save(self) -> None:
        target = self.run_dir / EXPERIMENT_FILE
        temp = target.with_suffix(".tmp")
        temp.write_text(json.dumps(self.record, indent=2), encoding="utf-8")
        temp.replace(target)

    # ------------------------------------------------------------ helpers

    @property
    def experiment_id(self) -> str:
        return str(self.record["experiment_id"])

    @property
    def checkpoints_dir(self) -> Path:
        return self.run_dir / CHECKPOINTS_DIR

    @property
    def reports_dir(self) -> Path:
        return self.run_dir / REPORTS_DIR

    @property
    def export_dir(self) -> Path:
        return self.run_dir / EXPORT_DIR
