"""Tensor validation: every way an input can disagree with the contract."""

import numpy as np
import pytest

from guardian_edge.application.inference.validation import (
    resolve_shape,
    validate_inputs,
    validate_tensor,
)
from guardian_edge.domain.errors import TensorValidationError
from guardian_edge.domain.model import TensorSpec

IMAGE_SPEC = TensorSpec(name="image", dtype="float32", shape=(None, 3, None, None))
FIXED_SPEC = TensorSpec(name="params", dtype="int64", shape=(1, 4))


def image(batch: int = 1, height: int = 480, width: int = 640) -> np.ndarray:
    return np.zeros((batch, 3, height, width), dtype=np.float32)


class TestValidateInputs:
    def test_accepts_valid_inputs(self) -> None:
        validate_inputs([IMAGE_SPEC], {"image": image()})

    def test_dynamic_dimensions_accept_any_size(self) -> None:
        validate_inputs([IMAGE_SPEC], {"image": image(height=64, width=1280)})

    def test_rejects_missing_tensor(self) -> None:
        with pytest.raises(TensorValidationError, match="missing"):
            validate_inputs([IMAGE_SPEC, FIXED_SPEC], {"image": image()})

    def test_rejects_unknown_tensor(self) -> None:
        with pytest.raises(TensorValidationError, match="unknown"):
            validate_inputs([IMAGE_SPEC], {"image": image(), "extra": image()})


class TestValidateTensor:
    def test_rejects_batch_size_other_than_one(self) -> None:
        with pytest.raises(TensorValidationError, match="batch size must be 1"):
            validate_tensor(IMAGE_SPEC, image(batch=2))

    def test_rejects_wrong_dtype(self) -> None:
        wrong = np.zeros((1, 3, 480, 640), dtype=np.float64)
        with pytest.raises(TensorValidationError, match="dtype"):
            validate_tensor(IMAGE_SPEC, wrong)

    def test_rejects_wrong_rank(self) -> None:
        with pytest.raises(TensorValidationError, match="rank"):
            validate_tensor(IMAGE_SPEC, np.zeros((3, 480, 640), dtype=np.float32))

    def test_rejects_fixed_dimension_mismatch(self) -> None:
        with pytest.raises(TensorValidationError, match="axis 1"):
            validate_tensor(FIXED_SPEC, np.zeros((1, 5), dtype=np.int64))

    def test_rejects_non_tensor_values(self) -> None:
        with pytest.raises(TensorValidationError, match="not a tensor"):
            validate_tensor(IMAGE_SPEC, [[1.0, 2.0]])


class TestResolveShape:
    def test_dynamic_dimensions_default_to_one(self) -> None:
        assert resolve_shape(IMAGE_SPEC) == (1, 3, 1, 1)

    def test_overrides_win(self) -> None:
        assert resolve_shape(IMAGE_SPEC, {"image": (1, 3, 480, 640)}) == (1, 3, 480, 640)

    def test_override_with_wrong_rank_is_rejected(self) -> None:
        with pytest.raises(TensorValidationError, match="rank"):
            resolve_shape(IMAGE_SPEC, {"image": (1, 3, 480)})
