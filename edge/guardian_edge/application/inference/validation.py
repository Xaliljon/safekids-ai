"""Tensor validation against a model's declared contract.

Pure functions over duck-typed arrays (anything with ``.shape`` and
``.dtype``), so the application layer never imports a tensor library.
Every violation is a precise, loggable TensorValidationError — a model fed
wrong data must fail loudly at the boundary, not silently misdetect
(docs/03: validate everything; this is a safety system).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from guardian_edge.domain.errors import TensorValidationError
from guardian_edge.domain.model import TensorSpec

REQUIRED_BATCH_SIZE = 1
"""The runtime processes exactly one sample per call (ADR-0008)."""


def validate_inputs(specs: Sequence[TensorSpec], inputs: Mapping[str, Any]) -> None:
    """Validate named input tensors against the manifest's input specs.

    Checks: exact name set, tensor-likeness, dtype, rank, fixed dimensions,
    and batch size 1 on the (conventionally first) batch dimension. Dynamic
    dimensions (``None``) accept any positive size — that is how dynamic
    input shapes stay safe.
    """
    expected = {spec.name for spec in specs}
    provided = set(inputs.keys())
    if missing := expected - provided:
        raise TensorValidationError(f"missing input tensor(s): {sorted(missing)}")
    if unknown := provided - expected:
        raise TensorValidationError(
            f"unknown input tensor(s): {sorted(unknown)} (model expects {sorted(expected)})"
        )
    for spec in specs:
        validate_tensor(spec, inputs[spec.name])


def validate_tensor(spec: TensorSpec, tensor: Any) -> None:
    """Validate one tensor against its spec."""
    shape = getattr(tensor, "shape", None)
    dtype = getattr(tensor, "dtype", None)
    if shape is None or dtype is None:
        raise TensorValidationError(
            f"input '{spec.name}' is not a tensor (missing shape/dtype): {type(tensor).__name__}"
        )
    if str(dtype) != spec.dtype:
        raise TensorValidationError(
            f"input '{spec.name}': dtype {dtype} does not match declared {spec.dtype}"
        )
    actual = tuple(int(dim) for dim in shape)
    if len(actual) != len(spec.shape):
        raise TensorValidationError(
            f"input '{spec.name}': rank {len(actual)} does not match declared "
            f"{len(spec.shape)} (shape {actual} vs {_format_shape(spec.shape)})"
        )
    for axis, (declared, got) in enumerate(zip(spec.shape, actual, strict=True)):
        if declared is None:
            if axis == 0 and got != REQUIRED_BATCH_SIZE:
                raise TensorValidationError(
                    f"input '{spec.name}': batch size must be {REQUIRED_BATCH_SIZE}, got {got}"
                )
            if got < 1:
                raise TensorValidationError(
                    f"input '{spec.name}': axis {axis} must be positive, got {got}"
                )
        elif declared != got:
            raise TensorValidationError(
                f"input '{spec.name}': axis {axis} is {got}, declared {declared} "
                f"(shape {actual} vs {_format_shape(spec.shape)})"
            )


def resolve_shape(
    spec: TensorSpec, overrides: Mapping[str, tuple[int, ...]] | None = None
) -> tuple[int, ...]:
    """Concrete shape for synthetic tensors (warmup): overrides win,
    otherwise dynamic dimensions resolve to 1."""
    if overrides is not None and spec.name in overrides:
        shape = overrides[spec.name]
        if len(shape) != len(spec.shape):
            raise TensorValidationError(
                f"warmup shape for '{spec.name}' has rank {len(shape)}, declared {len(spec.shape)}"
            )
        return shape
    return tuple(dim if dim is not None else 1 for dim in spec.shape)


def _format_shape(shape: tuple[int | None, ...]) -> str:
    return "(" + ", ".join("?" if dim is None else str(dim) for dim in shape) + ")"
