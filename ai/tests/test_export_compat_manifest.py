"""Guardian compatibility check + automatic manifest generation."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from guardian_ai.export.compat import ALLOWED_LICENSES, check_compatibility
from guardian_ai.export.manifest import (
    MANIFEST_FILE,
    build_manifest,
    load_manifest,
    save_manifest,
)
from guardian_ai.export.onnx_export import MODEL_FILE, export_onnx
from guardian_ai.training.errors import CompatibilityError
from guardian_ai.training.families import TinySsdFamily

LABELS = ["adult", "child", "person"]


def make_manifest(sha256: str, **overrides: Any) -> dict[str, Any]:
    manifest = build_manifest(
        model_name="tiny-ssd",
        model_version="0.0.1",
        sha256=sha256,
        labels=LABELS,
        license_id="Proprietary-GuardianAI",
        input_name="images",
        output_name="output",
        input_shape=[1, 3, 64, 64],
        output_shape=[1, 8],
        dataset_name="tiny-synthetic",
        dataset_version="1.0.0",
        taxonomy_name="guardian-safety",
        taxonomy_version="1.0.0",
        experiment_id="test-run-abc123",
        git_commit="deadbeef",
    )
    manifest.update(overrides)
    return manifest


@pytest.fixture(scope="module")
def artifact(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, str]:
    family = TinySsdFamily()
    model = family.build(num_classes=3, input_size=64)
    destination = tmp_path_factory.mktemp("export") / MODEL_FILE
    sha256 = export_onnx(model, family, 64, destination)
    return destination, sha256


def test_manifest_records_full_provenance(artifact: tuple[Path, str]) -> None:
    _, sha256 = artifact
    manifest = make_manifest(sha256)
    assert manifest["task"] == "object-detection"
    assert manifest["compatibility"] == {"schema": 1, "min_edge_version": "0.1.0"}
    training = manifest["metadata"]["training"]
    assert training["dataset"] == {"name": "tiny-synthetic", "version": "1.0.0"}
    assert training["experiment_id"] == "test-run-abc123"
    assert training["git_commit"] == "deadbeef"
    assert training["trained_utc"]


def test_manifest_save_load_roundtrip(artifact: tuple[Path, str], tmp_path: Path) -> None:
    _, sha256 = artifact
    manifest = make_manifest(sha256)
    path = save_manifest(manifest, tmp_path)
    assert path.name == MANIFEST_FILE
    assert load_manifest(tmp_path) == manifest


def test_valid_pair_passes_every_clause(artifact: tuple[Path, str]) -> None:
    path, sha256 = artifact
    passed = check_compatibility(path, make_manifest(sha256))
    assert any("batch=1" in clause for clause in passed)
    assert any("license" in clause for clause in passed)
    assert len(passed) >= 7


def test_sha_mismatch_is_rejected(artifact: tuple[Path, str]) -> None:
    path, _ = artifact
    with pytest.raises(CompatibilityError, match="sha256"):
        check_compatibility(path, make_manifest("0" * 64))


def test_disallowed_license_is_rejected(artifact: tuple[Path, str]) -> None:
    path, sha256 = artifact
    assert "AGPL-3.0" not in ALLOWED_LICENSES
    with pytest.raises(CompatibilityError, match="ADR-0003"):
        check_compatibility(path, make_manifest(sha256, license="AGPL-3.0"))


def test_missing_manifest_field_is_rejected(artifact: tuple[Path, str]) -> None:
    path, sha256 = artifact
    manifest = make_manifest(sha256)
    del manifest["compatibility"]
    with pytest.raises(CompatibilityError, match="missing required field"):
        check_compatibility(path, manifest)


def test_wrong_input_name_is_rejected(artifact: tuple[Path, str]) -> None:
    path, sha256 = artifact
    manifest = make_manifest(sha256)
    manifest["inputs"][0]["name"] = "tensor_0"
    with pytest.raises(CompatibilityError, match="input"):
        check_compatibility(path, manifest)


def test_unknown_output_is_rejected(artifact: tuple[Path, str]) -> None:
    path, sha256 = artifact
    manifest = make_manifest(sha256)
    manifest["outputs"] = [{"name": "detections", "dtype": "float32", "shape": [1, 8]}]
    with pytest.raises(CompatibilityError, match="outputs"):
        check_compatibility(path, manifest)


def test_empty_labels_are_rejected(artifact: tuple[Path, str]) -> None:
    path, sha256 = artifact
    manifest = make_manifest(sha256)
    manifest["metadata"]["labels"] = []
    with pytest.raises(CompatibilityError, match="labels"):
        check_compatibility(path, manifest)


def test_unsupported_schema_is_rejected(artifact: tuple[Path, str]) -> None:
    path, sha256 = artifact
    manifest = make_manifest(sha256)
    manifest["compatibility"]["schema"] = 2
    with pytest.raises(CompatibilityError, match="schema"):
        check_compatibility(path, manifest)


def test_wrong_file_name_is_rejected(artifact: tuple[Path, str]) -> None:
    path, sha256 = artifact
    with pytest.raises(CompatibilityError, match="artifact"):
        check_compatibility(path, make_manifest(sha256, file="other.onnx"))


def test_missing_model_file_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(CompatibilityError, match="missing"):
        check_compatibility(tmp_path / MODEL_FILE, make_manifest("0" * 64))


def test_non_batch1_model_is_rejected(tmp_path: Path) -> None:
    import torch

    family = TinySsdFamily()
    model = family.build(num_classes=3, input_size=64)
    destination = tmp_path / MODEL_FILE
    example = torch.zeros(2, 3, 64, 64)
    torch.onnx.export(
        model,
        (example,),
        str(destination),
        input_names=["images"],
        output_names=["output"],
        opset_version=17,
        dynamo=False,
        dynamic_axes={"images": {0: "batch"}, "output": {0: "batch"}},
    )
    from guardian_ai.export.onnx_export import sha256_of

    with pytest.raises(CompatibilityError, match="batch"):
        check_compatibility(destination, make_manifest(sha256_of(destination)))


def test_missing_min_edge_version_is_rejected(artifact: tuple[Path, str]) -> None:
    path, sha256 = artifact
    manifest = make_manifest(sha256)
    manifest["compatibility"] = {"schema": 1}
    with pytest.raises(CompatibilityError, match="min_edge_version"):
        check_compatibility(path, manifest)


def _handmade_model(tmp_path: Path, elem_type: int, dims: list) -> Path:
    """Minimal hand-built ONNX graph for contract edge cases."""
    import onnx
    from onnx import helper

    tensor_in = helper.make_tensor_value_info("images", elem_type, dims)
    tensor_out = helper.make_tensor_value_info("output", elem_type, dims)
    node = helper.make_node("Identity", ["images"], ["output"])
    graph = helper.make_graph([node], "handmade", [tensor_in], [tensor_out])
    model = helper.make_model(graph, opset_imports=[helper.make_opsetid("", 17)], ir_version=10)
    path = tmp_path / MODEL_FILE
    onnx.save(model, str(path))
    return path


def test_non_float32_input_is_rejected(tmp_path: Path) -> None:
    import onnx

    from guardian_ai.export.onnx_export import sha256_of

    path = _handmade_model(tmp_path, onnx.TensorProto.DOUBLE, [1, 3, 64, 64])
    with pytest.raises(CompatibilityError, match="float32"):
        check_compatibility(path, make_manifest(sha256_of(path)))


def test_non_nchw_input_is_rejected(tmp_path: Path) -> None:
    import onnx

    from guardian_ai.export.onnx_export import sha256_of

    path = _handmade_model(tmp_path, onnx.TensorProto.FLOAT, [1, 8])
    with pytest.raises(CompatibilityError, match="NCHW"):
        check_compatibility(path, make_manifest(sha256_of(path)))


def test_dynamic_spatial_dims_are_accepted(tmp_path: Path) -> None:
    import onnx

    from guardian_ai.export.onnx_export import sha256_of

    path = _handmade_model(tmp_path, onnx.TensorProto.FLOAT, [1, 3, "height", "width"])
    passed = check_compatibility(path, make_manifest(sha256_of(path)))
    assert any("dynamic supported" in clause for clause in passed)
