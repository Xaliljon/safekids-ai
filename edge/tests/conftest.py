"""Shared fixtures for the inference runtime tests.

Builds tiny synthetic ONNX graphs (Identity / Add) with the `onnx` helper —
these are test artifacts exercising the runtime, not AI models.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from onnx import TensorProto, helper, save

DYNAMIC_MODEL_NAME = "identity-dynamic"
FIXED_MODEL_NAME = "identity-fixed"


def build_identity_model(path: Path, dynamic: bool) -> None:
    """float32 Identity graph; dynamic variant has symbolic H/W dimensions."""
    shape: list[Any] = [1, 3, "height", "width"] if dynamic else [1, 4]
    node = helper.make_node("Identity", ["input"], ["output"])
    graph = helper.make_graph(
        [node],
        "identity",
        [helper.make_tensor_value_info("input", TensorProto.FLOAT, shape)],
        [helper.make_tensor_value_info("output", TensorProto.FLOAT, shape)],
    )
    model = helper.make_model(graph, opset_imports=[helper.make_opsetid("", 17)])
    save(model, str(path))


def manifest_dict(name: str, dynamic: bool, sha256: str | None = None) -> dict[str, Any]:
    shape = [1, 3, None, None] if dynamic else [1, 4]
    manifest: dict[str, Any] = {
        "name": name,
        "version": "1.0.0",
        "task": "test",
        "file": "model.onnx",
        "inputs": [{"name": "input", "dtype": "float32", "shape": shape}],
        "outputs": [{"name": "output", "dtype": "float32", "shape": shape}],
    }
    if sha256 is not None:
        manifest["sha256"] = sha256
    return manifest


def install_model(
    root: Path,
    name: str,
    version: str = "1.0.0",
    dynamic: bool = True,
    with_checksum: bool = True,
    manifest_overrides: dict[str, Any] | None = None,
) -> Path:
    """Create <root>/<name>/<version>/{model.onnx,manifest.json}; returns the dir."""
    version_dir = root / name / version
    version_dir.mkdir(parents=True)
    model_path = version_dir / "model.onnx"
    build_identity_model(model_path, dynamic=dynamic)
    sha256 = hashlib.sha256(model_path.read_bytes()).hexdigest() if with_checksum else None
    manifest = manifest_dict(name, dynamic=dynamic, sha256=sha256)
    manifest["version"] = version
    if manifest_overrides:
        manifest.update(manifest_overrides)
    (version_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return version_dir


@pytest.fixture(scope="session")
def dynamic_model_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A registry root containing the dynamic-shape identity model."""
    root = tmp_path_factory.mktemp("models-dynamic")
    install_model(root, DYNAMIC_MODEL_NAME, dynamic=True)
    return root


# --- synthetic object detection model (Sprint 5) ---------------------------

DETECTION_MODEL_NAME = "dummy-onnx-detector"

DETECTION_ROWS: list[list[float]] = [
    # x, y, width, height, confidence, class_index — normalized, top-left
    [0.10, 0.20, 0.30, 0.30, 0.90, 0],  # strong "person"
    [0.12, 0.22, 0.30, 0.30, 0.70, 0],  # overlaps the first -> NMS suppresses
    [0.60, 0.60, 0.20, 0.20, 0.30, 1],  # weak "child" -> confidence filter drops
]


def build_detection_model(path: Path, rows: list[list[float]]) -> None:
    """Graph with an image input and a constant [1, N, 6] detections output.

    The input is declared (and validated/fed) but unused — the "model"
    always reports the same detections, which is exactly what a runtime
    test wants: known output, real ONNX execution.
    """
    import numpy as np

    data = np.asarray([rows], dtype=np.float32)
    constant = helper.make_node(
        "Constant",
        [],
        ["detections"],
        value=helper.make_tensor(
            "detections_value", TensorProto.FLOAT, data.shape, data.flatten().tolist()
        ),
    )
    graph = helper.make_graph(
        [constant],
        "dummy-detector",
        [helper.make_tensor_value_info("image", TensorProto.FLOAT, [1, 3, "height", "width"])],
        [helper.make_tensor_value_info("detections", TensorProto.FLOAT, list(data.shape))],
    )
    save(helper.make_model(graph, opset_imports=[helper.make_opsetid("", 17)]), str(path))


def install_detection_model(
    root: Path,
    rows: list[list[float]] | None = None,
    metadata: dict[str, Any] | None = None,
    name: str = DETECTION_MODEL_NAME,
) -> Path:
    """Create a registry entry for the synthetic detection model."""
    rows = rows if rows is not None else DETECTION_ROWS
    version_dir = root / name / "1.0.0"
    version_dir.mkdir(parents=True)
    model_path = version_dir / "model.onnx"
    build_detection_model(model_path, rows)
    manifest: dict[str, Any] = {
        "name": name,
        "version": "1.0.0",
        "task": "object-detection",
        "file": "model.onnx",
        "sha256": hashlib.sha256(model_path.read_bytes()).hexdigest(),
        "inputs": [{"name": "image", "dtype": "float32", "shape": [1, 3, None, None]}],
        "outputs": [{"name": "detections", "dtype": "float32", "shape": [1, len(rows), 6]}],
        "metadata": metadata
        if metadata is not None
        else {"labels": ["person", "child"], "confidence_threshold": 0.5},
    }
    (version_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return version_dir


@pytest.fixture(scope="session")
def detection_model_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A registry root containing the synthetic detection model."""
    root = tmp_path_factory.mktemp("models-detection")
    install_detection_model(root)
    return root


# --- model bundles (Sprint 6, zoo installs) --------------------------------


def build_bundle(
    bundle_dir: Path,
    name: str = "bundled-model",
    version: str = "1.0.0",
    license_id: str | None = "Apache-2.0",
    with_checksum: bool = True,
    compatibility: dict[str, Any] | None = None,
    corrupt_after_hashing: bool = False,
) -> Path:
    """Author an installable model bundle directory (manifest + artifact)."""
    bundle_dir.mkdir(parents=True, exist_ok=True)
    model_path = bundle_dir / "model.onnx"
    build_identity_model(model_path, dynamic=True)
    manifest = manifest_dict(
        name,
        dynamic=True,
        sha256=hashlib.sha256(model_path.read_bytes()).hexdigest() if with_checksum else None,
    )
    manifest["version"] = version
    if license_id is not None:
        manifest["license"] = license_id
    if compatibility is not None:
        manifest["compatibility"] = compatibility
    (bundle_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    if corrupt_after_hashing:
        model_path.write_bytes(model_path.read_bytes() + b"tampered")
    return bundle_dir
