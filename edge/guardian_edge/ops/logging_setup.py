"""Structured, rotated logging for the pilot box.

One JSON-lines file per subsystem, size-rotated — logs can never grow
unbounded (a full disk on a safety device is an outage). Log records
carry no video, no images, no personal data (docs/03 logging rules);
the payloads that flow through the system are metadata-only by
construction (ADR-0014).
"""

from __future__ import annotations

import json
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

DEFAULT_MAX_BYTES = 5 * 1024 * 1024
DEFAULT_BACKUP_COUNT = 3

SUBSYSTEM_LOGS: dict[str, str] = {
    "guardian_edge.application.vision": "vision.log",
    "guardian_edge.infrastructure.vision": "vision.log",
    "guardian_edge.infrastructure.tracking": "tracking.log",
    "guardian_edge.application.events": "risk.log",
    "guardian_edge.application.risk": "risk.log",
    "guardian_edge.application.notifications": "notifications.log",
    "guardian_edge.infrastructure.notifications": "notifications.log",
    "guardian_edge.api": "device_api.log",
    "guardian_edge.ops.installer": "installer.log",
}
SYSTEM_LOG = "system.log"


class JsonLineFormatter(logging.Formatter):
    """One JSON object per line: timestamp, level, logger, message."""

    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(entry, ensure_ascii=False)


def configure_logging(
    logs_dir: Path,
    level: int = logging.INFO,
    max_bytes: int = DEFAULT_MAX_BYTES,
    backup_count: int = DEFAULT_BACKUP_COUNT,
    console: bool = True,
) -> None:
    """Route subsystem loggers to their rotated JSON files.

    Everything else lands in system.log via the root logger. Idempotent:
    repeated calls replace previously installed guardian handlers.
    """
    logs_dir.mkdir(parents=True, exist_ok=True)
    formatter = JsonLineFormatter()

    def handler_for(file_name: str) -> RotatingFileHandler:
        handler = RotatingFileHandler(
            logs_dir / file_name, maxBytes=max_bytes, backupCount=backup_count, encoding="utf-8"
        )
        handler.setFormatter(formatter)
        handler.set_name(f"guardian:{file_name}")
        return handler

    root = logging.getLogger()
    root.setLevel(level)
    _remove_guardian_handlers(root)
    root.addHandler(handler_for(SYSTEM_LOG))
    if console:
        stream = logging.StreamHandler()
        stream.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
        stream.set_name("guardian:console")
        root.addHandler(stream)

    handlers_by_file: dict[str, RotatingFileHandler] = {}
    for logger_name, file_name in SUBSYSTEM_LOGS.items():
        logger = logging.getLogger(logger_name)
        _remove_guardian_handlers(logger)
        if file_name not in handlers_by_file:
            handlers_by_file[file_name] = handler_for(file_name)
        logger.addHandler(handlers_by_file[file_name])
        logger.propagate = True  # system.log keeps the complete picture


def _remove_guardian_handlers(logger: logging.Logger) -> None:
    for handler in list(logger.handlers):
        if (handler.name or "").startswith("guardian:"):
            logger.removeHandler(handler)
            handler.close()
