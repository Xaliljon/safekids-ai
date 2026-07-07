"""Workspace artifacts: configs, colab notebook, dummy dataset script."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest
import yaml

from guardian_ai.datasets.registry import FileSystemDatasetRegistry
from guardian_ai.training.config import config_from_dict
from guardian_ai.training.errors import TrainingConfigurationError
from guardian_ai.training.families import get_family

TRAINING_DIR = Path(__file__).resolve().parents[1] / "training"


def test_workspace_layout_exists() -> None:
    for name in ("configs", "datasets", "models", "scripts", "notebooks", "reports", "runs"):
        assert (TRAINING_DIR / name).is_dir(), f"ai/training/{name} missing"
    assert (TRAINING_DIR / ".gitignore").is_file()


def test_smoke_config_is_valid_and_trainable() -> None:
    raw = yaml.safe_load((TRAINING_DIR / "configs" / "smoke.yaml").read_text())
    config = config_from_dict(raw, source="smoke.yaml")
    assert config.model.family == "tiny-ssd"
    get_family(config.model.family)  # must resolve


def test_training_template_is_valid_but_gated(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # training.yaml has no dataset.registry_root (Sprint 20: resolved via
    # GUARDIAN_DATASET_ROOT, never a hardcoded repo-relative path).
    monkeypatch.setenv("GUARDIAN_DATASET_ROOT", str(tmp_path))
    raw = yaml.safe_load((TRAINING_DIR / "configs" / "training.yaml").read_text())
    config = config_from_dict(raw, source="training.yaml")
    # rt-detr is scheduled after yolox-tiny; the reservation gate still fires loudly
    with pytest.raises(TrainingConfigurationError, match="scheduled after YOLOX-tiny"):
        get_family(config.model.family)


def test_dummy_dataset_script_publishes_through_registry(tmp_path: Path) -> None:
    spec = importlib.util.spec_from_file_location(
        "make_dummy_dataset", TRAINING_DIR / "scripts" / "make_dummy_dataset.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    registry_root = tmp_path / "registry"
    summary = module.build_and_publish(registry_root, "dummy-detection", "1.0.0", seed=1)
    assert summary["splits"] == {"train": 24, "val": 8, "test": 8}

    dataset = FileSystemDatasetRegistry(registry_root).get("dummy-detection")
    assert dataset.manifest.version == "1.0.0"
    records = dataset.load_split("train")
    assert len(records) == 24
    for record in records[:3]:
        assert (dataset.root / "media" / record.path).is_file()


class TestColabNotebook:
    @pytest.fixture(scope="class")
    def notebook(self) -> dict:
        return json.loads((TRAINING_DIR / "notebooks" / "colab.ipynb").read_text(encoding="utf-8"))

    def test_is_valid_nbformat4(self, notebook: dict) -> None:
        assert notebook["nbformat"] == 4
        assert notebook["cells"]

    def test_covers_the_mandated_workflow(self, notebook: dict) -> None:
        source = "\n".join("".join(cell["source"]) for cell in notebook["cells"])
        for required in (
            "drive.mount",  # mount Google Drive
            "pip install",  # install dependencies
            "make_dummy_dataset.py",  # download/prepare dataset
            "guardian_ai.train train",  # run training
            "guardian_ai.train evaluate",  # run evaluation
            "guardian_ai.train export",  # export ONNX
            "cp {RUN}/export/model.onnx",  # copy final ONNX
        ):
            assert required in source, f"colab.ipynb is missing step: {required}"

    def test_explains_each_step_in_markdown(self, notebook: dict) -> None:
        markdown = [cell for cell in notebook["cells"] if cell["cell_type"] == "markdown"]
        code = [cell for cell in notebook["cells"] if cell["cell_type"] == "code"]
        assert len(markdown) >= len(code)  # every code cell has an explanation

    def test_never_promotes_from_colab(self, notebook: dict) -> None:
        code = "\n".join(
            "".join(cell["source"]) for cell in notebook["cells"] if cell["cell_type"] == "code"
        )
        assert "promote" not in code  # promotion is never runnable from Colab
        assert "promotion stays manual" in code
