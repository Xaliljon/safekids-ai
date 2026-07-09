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
        "guardian_ai.train train",  # training (spec config referenced below)
        "ai/training/configs/model-v1.yaml",  # the exact Sprint 20 spec config
        "guardian_ai.train evaluate",  # evaluation
        "guardian_ai.train error-analysis",  # error analysis
        "guardian_ai.train qualitative",  # qualitative report
        "guardian_ai.train export",  # ONNX export
        "guardian_ai.train benchmark",  # benchmark
        "guardian_ai.train coco-compare",  # COCO-pretrained comparison
        "guardian_ai.train candidate",  # candidate marking
    ):
        assert required in source, f"model-v1-training.ipynb is missing step: {required}"


def test_no_longer_clones_git_or_copies_a_registry_folder(notebook: dict) -> None:
    """Sprint 20: workspace comes from zips, not git clone + a copied
    registry folder."""
    source = "\n".join("".join(cell["source"]) for cell in notebook["cells"])
    assert "git clone" not in source
    assert "cp -r" not in source


def test_dataset_root_is_set_automatically_and_validated(notebook: dict) -> None:
    """The bootstrap fix: GUARDIAN_DATASET_ROOT is set programmatically (no
    manual %env/export step) and the registry's existence is checked before
    training, aborting loudly rather than failing deep inside `train`."""
    code = "\n".join(
        "".join(cell["source"]) for cell in notebook["cells"] if cell["cell_type"] == "code"
    )
    assert 'os.environ["GUARDIAN_DATASET_ROOT"]' in code
    assert '"/content/datasets"' in code
    assert "registry_dir.is_dir()" in code
    assert "raise RuntimeError" in code


def test_installs_via_uv_not_plain_pip(notebook: dict) -> None:
    """Regression: `pip install -e ai` reliably fails on the pinned YOLOX
    git dependency (torch-at-build-time + onnx/onnxruntime version
    overrides are uv-only settings pip has no equivalent for — see
    architecture/training-platform.md). The notebook must use uv, and
    must never fall back to a bare `pip install -e ai`/`pip install -e .`."""
    code = "\n".join(
        "".join(cell["source"]) for cell in notebook["cells"] if cell["cell_type"] == "code"
    )
    assert "uv sync" in code
    assert "pip install -e" not in code
    assert "pip install -q -e" not in code


def test_train_cell_is_disconnect_resilient(notebook: dict) -> None:
    """Sprint 20.1: the run lives on Drive and re-running Run All resumes it,
    so a Colab disconnect before 30 epochs needs no manual resume command."""
    code = "\n".join(
        "".join(cell["source"]) for cell in notebook["cells"] if cell["cell_type"] == "code"
    )
    assert "--auto-resume" in code
    assert "--output-dir" in code
    assert "/runs" in code  # run directory placed under the Drive output dir
    # no manual `resume` subcommand anywhere — Run All is sufficient
    assert "guardian_ai.train resume" not in code


def test_forces_headless_matplotlib_backend(notebook: dict) -> None:
    """Regression: Colab sets MPLBACKEND to an inline backend absent from
    our uv venv, so matplotlib crashes at import in every venv subprocess
    (validation, train, report). The notebook must force Agg."""
    code = "\n".join(
        "".join(cell["source"]) for cell in notebook["cells"] if cell["cell_type"] == "code"
    )
    assert 'os.environ["MPLBACKEND"] = "Agg"' in code


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
