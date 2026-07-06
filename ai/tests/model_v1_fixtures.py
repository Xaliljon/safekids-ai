"""Shared builders for Sprint 19 (YOLOX-tiny / video training) tests.

Publishes a tiny real ``guardian_dataset_v1`` video dataset — through the
actual Sprint 18 pipeline (workspace -> approve -> registry.publish) —
so ``VideoRegistryDataModule`` tests exercise the real training/ export
format, not a hand-typed stand-in.
"""

from __future__ import annotations

from pathlib import Path

from acquisition_fixtures import approve_workspace, build_workspace

from guardian_ai.acquisition.registry import VideoDatasetRegistry
from guardian_ai.training.config import DatasetConfig


def publish_tiny_video_dataset(
    root: Path,
    name: str = "tiny-video-dataset",
    version: str = "1.0.0",
    clip_count: int = 3,
) -> Path:
    """Builds, approves and publishes a tiny video dataset; returns the
    published version directory (what ``VideoDatasetRegistry.get()`` would
    return)."""
    workspace = build_workspace(root / "ws", clip_count=clip_count)
    approve_workspace(workspace, by="tests")
    registry = VideoDatasetRegistry(root / "registry")
    return registry.publish(workspace, name, version)


def video_dataset_config(
    root: Path,
    name: str = "tiny-video-dataset",
    version: str = "1.0.0",
    max_samples: int | None = None,
) -> DatasetConfig:
    return DatasetConfig(
        registry_root=root / "registry",
        name=name,
        version=version,
        format="video",
        max_samples=max_samples,
    )
