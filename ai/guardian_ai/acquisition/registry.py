"""Guardian Video Dataset Registry: immutable, gated, checksummed.

The registry mirrors the discipline of the Sprint-7 record registry and
the model zoo (ADR-0009/0010): versions under ``<root>/<name>/<version>/``
are immutable, publishes stage atomically, checksums are computed at
publish and re-verified on ``get()``.

Publish gates, all mandatory, in order:

    review state APPROVED  ->  quality (errors block)  ->  privacy
    (violations block)  ->  statistics PDF  ->  training-ready export
    ->  checksums  ->  atomic install  ->  review state PUBLISHED

A version that exists cannot be replaced — publish a new version.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from guardian_ai.acquisition.errors import DatasetPublishError, DatasetRegistryError
from guardian_ai.acquisition.privacy import check_privacy
from guardian_ai.acquisition.quality import validate_quality, write_quality_report
from guardian_ai.acquisition.review import ReviewState, ReviewWorkflow
from guardian_ai.acquisition.statistics import compute_statistics, generate_dataset_report
from guardian_ai.acquisition.training_export import TRAINING_DIR, export_training_ready
from guardian_ai.acquisition.workspace import DatasetWorkspace

logger = logging.getLogger(__name__)

VERSION_MANIFEST = "version.json"
CHECKSUMS_FILE = "checksums.json"
STAGING_DIR = ".staging"
_VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")


class VideoDatasetRegistry:
    """Published Guardian video datasets over a local directory tree."""

    def __init__(self, root: Path) -> None:
        self._root = root
        stale = root / STAGING_DIR
        if stale.is_dir():
            shutil.rmtree(stale, ignore_errors=True)

    # ------------------------------------------------------------- publish

    def publish(self, workspace: DatasetWorkspace, name: str, version: str) -> Path:
        """Run every gate and install an immutable dataset version."""
        if not _VERSION_RE.match(version):
            raise DatasetPublishError(f"'{version}' is not a semantic version (MAJOR.MINOR.PATCH)")
        destination = self._root / name / version
        if destination.exists():
            raise DatasetPublishError(
                f"dataset {name} v{version} already exists — versions are "
                "immutable; publish a new version instead"
            )

        workflow = ReviewWorkflow(workspace.root)
        workflow.require(ReviewState.APPROVED, action="publish")
        approval = workflow.approval()

        quality = validate_quality(workspace)
        write_quality_report(quality, workspace)
        if not quality.ok:
            details = "; ".join(
                f"{issue.clip_id or 'dataset'}: {issue.message}" for issue in quality.errors
            )
            raise DatasetPublishError(f"quality gate failed: {details}")

        privacy = check_privacy(workspace)
        if not privacy.ok:
            details = "; ".join(
                f"{violation.where}: {violation.message}" for violation in privacy.violations
            )
            raise DatasetPublishError(f"privacy gate failed: {details}")

        generate_dataset_report(workspace)
        statistics = compute_statistics(workspace)

        staging = self._root / STAGING_DIR / f"{name}-{version}-{uuid4().hex}"
        try:
            shutil.copytree(workspace.root, staging)
            export_training_ready(workspace, staging / TRAINING_DIR)
            ReviewWorkflow(staging).record(
                ReviewState.PUBLISHED,
                by=approval["by"],
                notes=f"published as {name} v{version}",
            )
            checksums = _hash_tree(staging)
            (staging / CHECKSUMS_FILE).write_text(json.dumps(checksums, indent=2), encoding="utf-8")
            (staging / VERSION_MANIFEST).write_text(
                json.dumps(
                    {
                        "name": name,
                        "version": version,
                        "published_utc": datetime.now(tz=timezone.utc).isoformat(),
                        "approved_by": approval["by"],
                        "approved_utc": approval["utc"],
                        "review_notes": approval["notes"],
                        "statistics": statistics,
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
            destination.parent.mkdir(parents=True, exist_ok=True)
            staging.rename(destination)
        finally:
            shutil.rmtree(staging, ignore_errors=True)
        logger.info("published dataset %s v%s (%d clips)", name, version, statistics["videos"])
        return destination

    # --------------------------------------------------------------- reads

    def versions(self, name: str) -> list[str]:
        base = self._root / name
        if not base.is_dir():
            return []
        found = [
            path.name for path in base.iterdir() if path.is_dir() and _VERSION_RE.match(path.name)
        ]
        return sorted(found, key=lambda value: tuple(int(part) for part in value.split(".")))

    def get(self, name: str, version: str | None = None) -> Path:
        """Resolve a published version (latest when omitted) and verify it."""
        if version is None:
            available = self.versions(name)
            if not available:
                raise DatasetRegistryError(f"no published versions of '{name}'")
            version = available[-1]
        path = self._root / name / version
        if not (path / VERSION_MANIFEST).is_file():
            raise DatasetRegistryError(f"dataset {name} v{version} is not published")
        self._verify(path)
        return path

    def version_manifest(self, name: str, version: str | None = None) -> dict[str, Any]:
        path = self.get(name, version)
        return dict(json.loads((path / VERSION_MANIFEST).read_text(encoding="utf-8")))

    # ----------------------------------------------------------- internals

    def _verify(self, path: Path) -> None:
        recorded = json.loads((path / CHECKSUMS_FILE).read_text(encoding="utf-8"))
        for relative, expected in recorded.items():
            file_path = path / relative
            if not file_path.is_file():
                raise DatasetRegistryError(f"published file missing: {file_path}")
            if _sha256(file_path) != expected:
                raise DatasetRegistryError(
                    f"checksum mismatch in published dataset: {file_path} — "
                    "published versions are immutable; this one was modified"
                )


def _hash_tree(root: Path) -> dict[str, str]:
    checksums: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if path.is_file():
            checksums[path.relative_to(root).as_posix()] = _sha256(path)
    return checksums


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()
