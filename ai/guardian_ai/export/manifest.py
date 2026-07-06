"""Automatic model manifests — no manual editing, ever.

The manifest mirrors the Guardian Model Zoo contract the Edge Box loads
(ADR-0009; see models/<name>/<version>/manifest.json on a box) and adds
training provenance: which dataset, which taxonomy, which experiment,
which commit. A hand-edited manifest is indistinguishable from a lie, so
this module is the only writer.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

MANIFEST_FILE = "manifest.json"
COMPATIBILITY_SCHEMA = 1
MIN_EDGE_VERSION = "0.1.0"


def build_manifest(
    model_name: str,
    model_version: str,
    sha256: str,
    labels: list[str],
    license_id: str,
    input_name: str,
    output_name: str,
    input_shape: list[int],
    output_shape: list[int],
    dataset_name: str,
    dataset_version: str,
    taxonomy_name: str,
    taxonomy_version: str,
    experiment_id: str,
    git_commit: str,
    trained_utc: str | None = None,
) -> dict[str, Any]:
    return {
        "name": model_name,
        "version": model_version,
        "task": "object-detection",
        "file": "model.onnx",
        "sha256": sha256,
        "license": license_id,
        "compatibility": {
            "schema": COMPATIBILITY_SCHEMA,
            "min_edge_version": MIN_EDGE_VERSION,
        },
        "inputs": [{"name": input_name, "dtype": "float32", "shape": input_shape}],
        "outputs": [{"name": output_name, "dtype": "float32", "shape": output_shape}],
        "metadata": {
            "labels": labels,
            "training": {
                "dataset": {"name": dataset_name, "version": dataset_version},
                "taxonomy": {"name": taxonomy_name, "version": taxonomy_version},
                "experiment_id": experiment_id,
                "git_commit": git_commit,
                "trained_utc": trained_utc or datetime.now(tz=timezone.utc).isoformat(),
            },
        },
    }


def save_manifest(manifest: dict[str, Any], directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / MANIFEST_FILE
    path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return path


def load_manifest(directory: Path) -> dict[str, Any]:
    return dict(json.loads((directory / MANIFEST_FILE).read_text(encoding="utf-8")))
