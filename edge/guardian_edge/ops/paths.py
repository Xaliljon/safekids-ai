"""The Guardian home directory: one root for everything a box owns.

$GUARDIAN_HOME/            (default: ~/guardian)
  config/cameras.yaml      camera registrations
  models/                  model zoo (ADR-0009 layout)
  data/                    outbox, trusted devices, runtime state
  logs/                    rotated structured logs
  backups/                 configuration backups
  reports/                 install/diagnostic reports, metric exports
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

GUARDIAN_HOME_ENV = "GUARDIAN_HOME"


@dataclass(frozen=True, slots=True)
class GuardianHome:
    root: Path

    @classmethod
    def from_env(cls) -> GuardianHome:
        return cls(Path(os.environ.get(GUARDIAN_HOME_ENV, str(Path.home() / "guardian"))))

    @property
    def config_dir(self) -> Path:
        return self.root / "config"

    @property
    def cameras_file(self) -> Path:
        return self.config_dir / "cameras.yaml"

    @property
    def models_dir(self) -> Path:
        return self.root / "models"

    @property
    def data_dir(self) -> Path:
        return self.root / "data"

    @property
    def outbox_dir(self) -> Path:
        return self.data_dir / "outbox"

    @property
    def logs_dir(self) -> Path:
        return self.root / "logs"

    @property
    def backups_dir(self) -> Path:
        return self.root / "backups"

    @property
    def reports_dir(self) -> Path:
        return self.root / "reports"

    def ensure(self) -> GuardianHome:
        """Create the directory tree; idempotent."""
        for path in (
            self.config_dir,
            self.models_dir,
            self.data_dir,
            self.outbox_dir,
            self.logs_dir,
            self.backups_dir,
            self.reports_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)
        return self
