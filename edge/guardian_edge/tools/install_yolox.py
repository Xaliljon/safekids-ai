"""Install the YOLOX-tiny detection model into a local model zoo.

Downloads the official Apache-2.0 ONNX release (ADR-0003), verifies the
pinned SHA-256, introspects the real graph I/O to author the manifest
(so the manifest can never lie about the graph), and installs through the
model zoo — the same gates an OTA bundle passes (ADR-0009).

Usage: uv run python -m guardian_edge.tools.install_yolox [--dest models]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import sys
import tempfile
import urllib.request
from pathlib import Path

import onnxruntime as ort

from guardian_edge.infrastructure.inference.zoo import FileSystemModelZoo
from guardian_edge.infrastructure.vision.yolox import COCO_LABELS, YOLOX_MODEL_NAME

logger = logging.getLogger("install_yolox")

DOWNLOAD_URL = (
    "https://github.com/Megvii-BaseDetection/YOLOX/releases/download/0.1.1rc0/yolox_tiny.onnx"
)
EXPECTED_SHA256 = "427cc366d34e27ff7a03e2899b5e3671425c262ea2291f88bb942bc1cc70b0f7"
MODEL_VERSION = "0.1.1-rc0"

_ORT_TO_DTYPE = {"tensor(float)": "float32"}


def install(dest: Path) -> Path:
    """Download, verify, and install; returns the installed version dir."""
    zoo = FileSystemModelZoo(dest)
    existing = dest / YOLOX_MODEL_NAME / MODEL_VERSION
    if existing.is_dir():
        logger.info("%s v%s already installed at %s", YOLOX_MODEL_NAME, MODEL_VERSION, existing)
        zoo.activate(YOLOX_MODEL_NAME, MODEL_VERSION)
        return existing

    with tempfile.TemporaryDirectory(prefix="yolox-bundle-") as staging:
        bundle = Path(staging)
        artifact = bundle / "model.onnx"
        logger.info("downloading %s", DOWNLOAD_URL)
        urllib.request.urlretrieve(DOWNLOAD_URL, artifact)  # noqa: S310 - pinned https URL, hash-verified below
        digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
        if digest != EXPECTED_SHA256:
            raise SystemExit(
                f"downloaded artifact hash {digest} does not match pinned "
                f"{EXPECTED_SHA256} — refusing to install"
            )
        (bundle / "manifest.json").write_text(
            json.dumps(_build_manifest(artifact, digest), indent=2), encoding="utf-8"
        )
        zoo.install(bundle, activate=True)
    installed = dest / YOLOX_MODEL_NAME / MODEL_VERSION
    logger.info("installed and activated %s v%s at %s", YOLOX_MODEL_NAME, MODEL_VERSION, installed)
    return installed


def _build_manifest(artifact: Path, sha256: str) -> dict[str, object]:
    """Author the manifest from the model's real graph — it cannot lie."""
    session = ort.InferenceSession(str(artifact), providers=["CPUExecutionProvider"])
    return {
        "name": YOLOX_MODEL_NAME,
        "version": MODEL_VERSION,
        "task": "object-detection",
        "file": "model.onnx",
        "sha256": sha256,
        "license": "Apache-2.0",
        "compatibility": {"schema": 1, "min_edge_version": "0.1.0"},
        "inputs": [_tensor_spec(node) for node in session.get_inputs()],
        "outputs": [_tensor_spec(node) for node in session.get_outputs()],
        "metadata": {
            "labels": list(COCO_LABELS),
            "confidence_threshold": 0.35,
            "nms_iou_threshold": 0.45,
            "source": DOWNLOAD_URL,
        },
    }


def _tensor_spec(node: object) -> dict[str, object]:
    name = getattr(node, "name", "")
    ort_type = getattr(node, "type", "")
    shape = getattr(node, "shape", [])
    dtype = _ORT_TO_DTYPE.get(str(ort_type))
    if dtype is None:
        raise SystemExit(f"unsupported tensor type '{ort_type}' for '{name}'")
    return {
        "name": str(name),
        "dtype": dtype,
        "shape": [dim if isinstance(dim, int) else None for dim in shape],
    }


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dest",
        type=Path,
        default=Path("models"),
        help="model zoo root directory (default: ./models)",
    )
    args = parser.parse_args(argv)
    install(args.dest)
    return 0


if __name__ == "__main__":
    sys.exit(main())
