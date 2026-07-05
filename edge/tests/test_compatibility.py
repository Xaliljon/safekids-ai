"""Model-runtime compatibility checks."""

import pytest

from guardian_edge.application.inference.compatibility import CompatibilityChecker
from guardian_edge.domain.detection import ModelDescriptor
from guardian_edge.domain.errors import ModelCompatibilityError, ModelValidationError
from guardian_edge.domain.model import ModelCompatibility, ModelManifest, TensorSpec


def make_manifest(compatibility: ModelCompatibility) -> ModelManifest:
    return ModelManifest(
        model=ModelDescriptor(name="test-model", version="1.0.0"),
        task="test",
        file_name="model.onnx",
        inputs=(TensorSpec(name="input", dtype="float32", shape=(1, 4)),),
        outputs=(TensorSpec(name="output", dtype="float32", shape=(1, 4)),),
        compatibility=compatibility,
    )


def checker() -> CompatibilityChecker:
    return CompatibilityChecker(edge_version="0.5.0", supported_schemas=(1,))


def test_default_compatibility_passes() -> None:
    checker().check(make_manifest(ModelCompatibility()))


def test_unknown_manifest_schema_is_refused() -> None:
    with pytest.raises(ModelCompatibilityError, match="schema 2"):
        checker().check(make_manifest(ModelCompatibility(schema=2)))


def test_min_edge_version_above_runtime_is_refused() -> None:
    with pytest.raises(ModelCompatibilityError, match="requires guardian-edge >= 1.0.0"):
        checker().check(make_manifest(ModelCompatibility(min_edge_version="1.0.0")))


@pytest.mark.parametrize("required", ["0.5.0", "0.4.9", "0.1.0"])
def test_min_edge_version_at_or_below_runtime_passes(required: str) -> None:
    checker().check(make_manifest(ModelCompatibility(min_edge_version=required)))


def test_invalid_min_edge_version_fails_at_construction() -> None:
    with pytest.raises(ModelValidationError):
        ModelCompatibility(min_edge_version="not-a-version")


def test_invalid_schema_fails_at_construction() -> None:
    with pytest.raises(ModelValidationError):
        ModelCompatibility(schema=0)
