"""ONNX export: an artifact is done only when validation passes."""

from __future__ import annotations

from pathlib import Path

import pytest

from guardian_ai.export.onnx_export import (
    MODEL_FILE,
    _validate_parity,
    _validate_structure,
    export_onnx,
    sha256_of,
)
from guardian_ai.training.errors import ExportRejectedError
from guardian_ai.training.families import TinySsdFamily


@pytest.fixture(scope="module")
def exported(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, object, TinySsdFamily]:
    family = TinySsdFamily()
    model = family.build(num_classes=3, input_size=64)
    destination = tmp_path_factory.mktemp("export") / MODEL_FILE
    sha256 = export_onnx(model, family, 64, destination)
    assert sha256 == sha256_of(destination)
    return destination, model, family


def test_export_produces_loadable_onnx(exported: tuple) -> None:
    import onnx

    path, _, family = exported
    model = onnx.load(str(path))
    graph_inputs = [i.name for i in model.graph.input]
    assert family.input_name() in graph_inputs
    assert [output.name for output in model.graph.output] == [family.output_name()]


def test_onnx_inference_matches_torch(exported: tuple) -> None:
    # export_onnx already enforced parity; assert it directly once more
    path, model, family = exported
    _validate_parity(model, family, path, 64, seed=42)


def test_truncated_artifact_is_rejected(exported: tuple, tmp_path: Path) -> None:
    path, _, _ = exported
    broken = tmp_path / MODEL_FILE
    broken.write_bytes(path.read_bytes()[: path.stat().st_size // 2])
    with pytest.raises(ExportRejectedError, match="structural check failed"):
        _validate_structure(broken)


def test_diverging_outputs_are_rejected(exported: tuple, tmp_path: Path) -> None:
    path, _, family = exported
    # a DIFFERENT model against the same artifact: parity must fail
    other = family.build(num_classes=3, input_size=64)
    with pytest.raises(ExportRejectedError, match="diverge"):
        _validate_parity(other, family, path, 64, seed=42)


def test_sha256_is_stable(exported: tuple) -> None:
    path, _, _ = exported
    assert sha256_of(path) == sha256_of(path)
    assert len(sha256_of(path)) == 64
