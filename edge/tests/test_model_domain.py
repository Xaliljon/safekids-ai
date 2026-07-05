"""TensorSpec and ModelManifest validation."""

import pytest

from guardian_edge.domain.detection import ModelDescriptor
from guardian_edge.domain.errors import ModelValidationError
from guardian_edge.domain.model import ModelManifest, TensorSpec

SPEC = TensorSpec(name="input", dtype="float32", shape=(1, 3, None, None))


def make_manifest(**overrides: object) -> ModelManifest:
    kwargs: dict[str, object] = {
        "model": ModelDescriptor(name="test-model", version="1.0.0"),
        "task": "test",
        "file_name": "model.onnx",
        "inputs": (SPEC,),
        "outputs": (TensorSpec(name="output", dtype="float32", shape=(1, 10)),),
    }
    kwargs.update(overrides)
    return ModelManifest(**kwargs)  # type: ignore[arg-type]


class TestTensorSpec:
    def test_accepts_dynamic_dimensions(self) -> None:
        assert SPEC.shape == (1, 3, None, None)

    def test_rejects_unknown_dtype(self) -> None:
        with pytest.raises(ModelValidationError, match="unknown dtype"):
            TensorSpec(name="input", dtype="complex128", shape=(1,))

    def test_rejects_blank_name(self) -> None:
        with pytest.raises(ModelValidationError):
            TensorSpec(name=" ", dtype="float32", shape=(1,))

    @pytest.mark.parametrize("dim", [0, -1])
    def test_rejects_non_positive_dimensions(self, dim: int) -> None:
        with pytest.raises(ModelValidationError):
            TensorSpec(name="input", dtype="float32", shape=(1, dim))


class TestModelManifest:
    def test_accepts_valid_manifest(self) -> None:
        assert make_manifest().model.name == "test-model"

    def test_rejects_empty_inputs(self) -> None:
        with pytest.raises(ModelValidationError, match="at least one input"):
            make_manifest(inputs=())

    def test_rejects_duplicate_tensor_names(self) -> None:
        with pytest.raises(ModelValidationError, match="duplicate"):
            make_manifest(inputs=(SPEC, SPEC))

    @pytest.mark.parametrize("field", ["task", "file_name"])
    def test_rejects_blank_required_fields(self, field: str) -> None:
        with pytest.raises(ModelValidationError):
            make_manifest(**{field: "  "})
