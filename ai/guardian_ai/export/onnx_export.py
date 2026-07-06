"""PyTorch → ONNX export with mandatory validation.

An export is not "done" when the file exists — it is done when the ONNX
checker passes AND onnxruntime reproduces the torch outputs on a fixed
input. Anything else is rejected: a broken artifact must never reach the
manifest step, let alone the zoo. The Edge Box consumes ONNX only;
PyTorch never crosses this boundary.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import numpy as np

from guardian_ai.training.errors import ExportRejectedError
from guardian_ai.training.families import DetectorFamily

MODEL_FILE = "model.onnx"
_OPSET = 17
_PARITY_ATOL = 1e-4


def export_onnx(
    model: Any,
    family: DetectorFamily,
    input_size: int,
    destination: Path,
    seed: int = 0,
) -> str:
    """Export, validate structurally, prove numeric parity; returns sha256."""
    import torch

    destination.parent.mkdir(parents=True, exist_ok=True)
    model.eval()
    example = torch.zeros(1, 3, input_size, input_size)
    torch.onnx.export(
        model,
        (example,),
        str(destination),
        input_names=[family.input_name()],
        output_names=[family.output_name()],
        opset_version=_OPSET,
        dynamo=False,
    )
    _validate_structure(destination)
    _validate_parity(model, family, destination, input_size, seed)
    return sha256_of(destination)


def _validate_structure(path: Path) -> None:
    import onnx

    try:
        model = onnx.load(str(path))
        onnx.checker.check_model(model)
    except Exception as exc:
        raise ExportRejectedError(f"ONNX structural check failed: {exc}") from exc


def _validate_parity(
    model: Any, family: DetectorFamily, path: Path, input_size: int, seed: int
) -> None:
    """One inference in both runtimes on the same input; outputs must agree."""
    import onnxruntime
    import torch

    generator = np.random.default_rng(seed)
    example = generator.standard_normal((1, 3, input_size, input_size)).astype(np.float32)
    with torch.no_grad():
        expected = model(torch.from_numpy(example)).cpu().numpy()
    try:
        session = onnxruntime.InferenceSession(str(path), providers=["CPUExecutionProvider"])
        (actual,) = session.run([family.output_name()], {family.input_name(): example})
    except Exception as exc:
        raise ExportRejectedError(f"ONNX inference failed: {exc}") from exc
    if actual.shape != expected.shape:
        raise ExportRejectedError(
            f"output shape mismatch: torch {expected.shape} vs onnx {actual.shape}"
        )
    worst = float(np.max(np.abs(actual - expected)))
    if worst > _PARITY_ATOL:
        raise ExportRejectedError(
            f"torch/onnx outputs diverge (max |Δ|={worst:.2e} > {_PARITY_ATOL:.0e}) — "
            "export rejected"
        )


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()
