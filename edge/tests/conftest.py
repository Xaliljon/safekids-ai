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
