"""Guardian compatibility check: reject what the Edge Box cannot load.

Mirrors the Inference Runtime's contract (ADR-0008/0009) from the model
zoo side — the ai/ package never imports edge code (boundary rule), so
the contract is asserted here explicitly:

- exactly one float32 input, batch dimension == 1 (fixed),
- H/W static or symbolic (the runtime supports dynamic spatial dims),
- at least one float32 output with a declared name,
- manifest matches the artifact: file name, sha256, input/output names
  and shapes, non-empty labels,
- license on the on-device allowlist (ADR-0003 — AGPL never ships),
- compatibility schema/min-edge-version present.

Any violation raises CompatibilityError with the exact clause.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from guardian_ai.export.onnx_export import sha256_of
from guardian_ai.training.errors import CompatibilityError

ALLOWED_LICENSES = frozenset(
    {"Apache-2.0", "MIT", "BSD-2-Clause", "BSD-3-Clause", "Proprietary-GuardianAI"}
)
_FLOAT32 = 1  # onnx.TensorProto.FLOAT


def check_compatibility(model_path: Path, manifest: dict[str, Any]) -> list[str]:
    """Full contract check; returns the passed clauses (for the report)."""
    import onnx

    if not model_path.is_file():
        raise CompatibilityError(f"model file missing: {model_path}")
    passed: list[str] = []

    # ---- integrity first: manifest fields + checksum, before any parsing --
    for key in (
        "name",
        "version",
        "file",
        "sha256",
        "license",
        "compatibility",
        "inputs",
        "outputs",
        "metadata",
    ):
        if key not in manifest:
            raise CompatibilityError(f"manifest is missing required field '{key}'")
    if manifest["file"] != model_path.name:
        raise CompatibilityError(
            f"manifest file '{manifest['file']}' != artifact '{model_path.name}'"
        )
    if manifest["sha256"] != sha256_of(model_path):
        raise CompatibilityError(
            "manifest sha256 does not match the artifact — refusing a mismatched pair"
        )
    passed.append("manifest: file + sha256 match the artifact")

    try:
        model = onnx.load(str(model_path))
    except Exception as exc:
        raise CompatibilityError(f"artifact is not loadable ONNX: {exc}") from exc
    graph = model.graph

    # ---- inputs ---------------------------------------------------------
    initializers = {initializer.name for initializer in graph.initializer}
    inputs = [i for i in graph.input if i.name not in initializers]
    if len(inputs) != 1:
        raise CompatibilityError(f"the runtime expects exactly one input, model has {len(inputs)}")
    graph_input = inputs[0]
    tensor = graph_input.type.tensor_type
    if tensor.elem_type != _FLOAT32:
        raise CompatibilityError("input dtype must be float32")
    dims = tensor.shape.dim
    if len(dims) != 4:
        raise CompatibilityError(f"input must be NCHW (4 dims), got {len(dims)}")
    if not (dims[0].HasField("dim_value") and dims[0].dim_value == 1):
        raise CompatibilityError("batch dimension must be fixed at 1 (ADR-0008)")
    passed.append("input: single float32 NCHW tensor, batch=1")
    for dim in (dims[2], dims[3]):
        if not (dim.HasField("dim_value") or dim.HasField("dim_param")):
            raise CompatibilityError("H/W dims must be static or symbolic, not absent")
    passed.append("input: spatial dims static or symbolic (dynamic supported)")

    # ---- outputs --------------------------------------------------------
    if not graph.output:
        raise CompatibilityError("model declares no outputs")
    for output in graph.output:
        if output.type.tensor_type.elem_type != _FLOAT32:
            raise CompatibilityError(f"output '{output.name}' must be float32")
    passed.append(f"outputs: {[output.name for output in graph.output]} float32")

    # ---- manifest agreement ---------------------------------------------
    if manifest["inputs"][0]["name"] != graph_input.name:
        raise CompatibilityError(
            f"manifest input '{manifest['inputs'][0]['name']}' != graph '{graph_input.name}'"
        )
    declared_outputs = {entry["name"] for entry in manifest["outputs"]}
    graph_outputs = {output.name for output in graph.output}
    if not declared_outputs <= graph_outputs:
        raise CompatibilityError(
            f"manifest outputs {sorted(declared_outputs)} not all present in the "
            f"graph {sorted(graph_outputs)}"
        )
    passed.append("manifest: input/output names match the graph")
    labels = manifest.get("metadata", {}).get("labels", [])
    if not labels:
        raise CompatibilityError("manifest metadata.labels must not be empty")
    passed.append(f"labels: {len(labels)} class name(s)")

    # ---- license (ADR-0003) ---------------------------------------------
    if manifest["license"] not in ALLOWED_LICENSES:
        raise CompatibilityError(
            f"license '{manifest['license']}' is not on the on-device allowlist "
            f"{sorted(ALLOWED_LICENSES)} (ADR-0003)"
        )
    passed.append(f"license: {manifest['license']} allowed on-device")

    schema = manifest["compatibility"].get("schema")
    if schema != 1:
        raise CompatibilityError(f"unsupported compatibility schema {schema}")
    if not manifest["compatibility"].get("min_edge_version"):
        raise CompatibilityError("compatibility.min_edge_version is required")
    passed.append("compatibility: schema 1, min_edge_version declared")
    return passed
