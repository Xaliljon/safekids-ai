"""Configuration backup and restore (ADR-0016).

The backup is an allowlist, not a filesystem dump: camera configuration
and trusted devices — the things a re-imaged box needs to become itself
again. Models re-install from the zoo pipeline, logs are ephemeral, and
video/images never exist on disk in the first place (metadata-only
pipeline); excluding them is enforced by construction.
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path
from typing import Any

import guardian_edge
from guardian_edge.domain.errors import GuardianEdgeError
from guardian_edge.ops.paths import GuardianHome

BACKUP_MANIFEST = "backup-manifest.json"
_ALLOWLIST: tuple[tuple[str, str], ...] = (
    # (path relative to home, restore destination relative to home)
    ("config/cameras.yaml", "config/cameras.yaml"),
    ("data/trusted_devices.json", "data/trusted_devices.json"),
)


class BackupError(GuardianEdgeError):
    """A backup archive is missing, malformed, or from an unknown source."""


def create_backup(home: GuardianHome, destination: Path, created_utc: str) -> dict[str, Any]:
    """Write a configuration backup archive; returns its manifest."""
    included: list[str] = []
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for relative, _ in _ALLOWLIST:
            source = home.root / relative
            if source.is_file():
                archive.write(source, arcname=relative)
                included.append(relative)
        manifest = {
            "created_utc": created_utc,
            "guardian_edge_version": guardian_edge.__version__,
            "files": included,
        }
        archive.writestr(BACKUP_MANIFEST, json.dumps(manifest, indent=2))
    return manifest


def restore_backup(archive_path: Path, home: GuardianHome) -> list[str]:
    """Restore an allowlisted backup into the home; returns restored files.

    Only known configuration paths are extracted — a hostile archive
    cannot write outside them.
    """
    if not archive_path.is_file():
        raise BackupError(f"backup archive not found: {archive_path}")
    restored: list[str] = []
    with zipfile.ZipFile(archive_path) as archive:
        names = set(archive.namelist())
        if BACKUP_MANIFEST not in names:
            raise BackupError(f"'{archive_path}' is not a Guardian backup (no manifest)")
        manifest = json.loads(archive.read(BACKUP_MANIFEST).decode("utf-8"))
        if "files" not in manifest:
            raise BackupError("backup manifest is malformed")
        for relative, target_relative in _ALLOWLIST:
            if relative not in names:
                continue
            target = home.root / target_relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(archive.read(relative))
            restored.append(target_relative)
    return restored
