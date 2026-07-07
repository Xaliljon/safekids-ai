"""Sprint 19/20 Colab notebook: structure smoke test (mirrors Sprint 17's)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

NOTEBOOK_PATH = (
    Path(__file__).resolve().parents[1] / "training" / "notebooks" / "model-v1-training.ipynb"
)


@pytest.fixture(scope="module")
def notebook() -> dict:
    return json.loads(NOTEBOOK_PATH.read_text(encoding="utf-8"))


def test_is_valid_nbformat4(notebook: dict) -> None:
    assert notebook["nbformat"] == 4
    assert notebook["cells"]


def test_targets_a_t4_gpu(notebook: dict) -> None:
    assert notebook["metadata"]["colab"]["gpuType"] == "T4"
    assert notebook["metadata"]["accelerator"] == "GPU"


def test_covers_the_mandated_sprint19_workflow(notebook: dict) -> None:
    source = "\n".join("".join(cell["source"]) for cell in notebook["cells"])
    for required in (
        "drive.mount",  # mount Google Drive
        "guardian-ai.zip",  # source-only package (scripts/package-colab.sh)
        "guardian-dataset-v1.zip",  # dataset package (scripts/package-dataset.sh)
        "GUARDIAN_DATASET_ROOT",  # datasets are external assets, never hardcoded
        "pip install",  # install dependencies
        "guardian-fall-detection-v1",  # the real published dataset
        "guardian_ai.train train --config ai/training/configs/model-v1.yaml",  # exact spec config
        "guardian_ai.train evaluate",  # evaluation
        "guardian_ai.train error-analysis",  # error analysis
        "guardian_ai.train qualitative",  # qualitative report
        "guardian_ai.train export",  # ONNX export
        "guardian_ai.train benchmark",  # benchmark
        "guardian_ai.train coco-compare",  # COCO-pretrained comparison
        "guardian_ai.train candidate",  # candidate marking
    ):
        assert required in source, f"model-v1-training.ipynb is missing step: {required}"


def test_no_longer_clones_git_or_hardcodes_the_dataset_path(notebook: dict) -> None:
    """Sprint 20: workspace comes from zips, not git clone + a copied
    registry folder; the dataset path is never hardcoded."""
    source = "\n".join("".join(cell["source"]) for cell in notebook["cells"])
    assert "git clone" not in source
    assert "datasets/registry" not in source


def test_explains_each_step_in_markdown(notebook: dict) -> None:
    markdown = [cell for cell in notebook["cells"] if cell["cell_type"] == "markdown"]
    code = [cell for cell in notebook["cells"] if cell["cell_type"] == "code"]
    assert len(markdown) >= len(code)


def test_never_installs_into_a_model_zoo(notebook: dict) -> None:
    code = "\n".join(
        "".join(cell["source"]) for cell in notebook["cells"] if cell["cell_type"] == "code"
    )
    assert "guardian_ai.train promote" not in code
    assert "candidate only" in code.lower() or "candidate model only" in code.lower()
