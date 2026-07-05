"""AI model identity and I/O contract (the manifest).

Pure Python. A ModelManifest is the domain's view of contracts/models: what
a model is called, which version it is, and exactly which tensors it accepts
and produces. Engines refuse to load models that disagree with their
manifest, and refuse inputs that disagree with the specs (ADR-0008) —
"models must be replaceable" only works if their contracts are explicit.
"""

from __future__ import annotations

from dataclasses import dataclass

from guardian_edge.domain.detection import ModelDescriptor
from guardian_edge.domain.errors import ModelValidationError

_KNOWN_DTYPES = frozenset(
    {
        "float16",
        "float32",
        "float64",
        "int8",
        "int16",
        "int32",
        "int64",
        "uint8",
        "uint16",
        "bool",
    }
)


@dataclass(frozen=True, slots=True)
class TensorSpec:
    """Contract for one named tensor.

    ``shape`` dimensions are either fixed ints or ``None`` for dynamic
    dimensions resolved at runtime (dynamic input shapes). By convention the
    first dimension is the batch dimension; the runtime enforces batch
    size 1 on it (ADR-0008).
    """

    name: str
    dtype: str
    shape: tuple[int | None, ...]

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ModelValidationError("tensor name must not be empty")
        if self.dtype not in _KNOWN_DTYPES:
            raise ModelValidationError(
                f"tensor '{self.name}': unknown dtype '{self.dtype}' "
                f"(expected one of {sorted(_KNOWN_DTYPES)})"
            )
        for dim in self.shape:
            if dim is not None and dim < 1:
                raise ModelValidationError(
                    f"tensor '{self.name}': dimensions must be positive or None, got {dim}"
                )


@dataclass(frozen=True, slots=True)
class ModelManifest:
    """Everything the runtime needs to know about one model artifact."""

    model: ModelDescriptor
    task: str
    file_name: str
    inputs: tuple[TensorSpec, ...]
    outputs: tuple[TensorSpec, ...]
    sha256: str | None = None
    """Optional artifact checksum; verified by the registry when present."""

    def __post_init__(self) -> None:
        if not self.task.strip():
            raise ModelValidationError(f"model '{self.model.name}': task must not be empty")
        if not self.file_name.strip():
            raise ModelValidationError(f"model '{self.model.name}': file_name must not be empty")
        if not self.inputs or not self.outputs:
            raise ModelValidationError(
                f"model '{self.model.name}': at least one input and one output are required"
            )
        for specs in (self.inputs, self.outputs):
            names = [spec.name for spec in specs]
            if len(names) != len(set(names)):
                raise ModelValidationError(
                    f"model '{self.model.name}': duplicate tensor names in {names}"
                )
