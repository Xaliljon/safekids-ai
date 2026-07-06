"""CLI end-to-end for the production family: yolox-tiny on a real (tiny)
published video dataset — train -> evaluate -> error-analysis ->
qualitative -> export -> benchmark -> candidate. ``coco-compare`` needs
network + the edge/ project; only its error path is exercised here (see
reports/model-v1/ for the real, manually-run comparison).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from model_v1_fixtures import publish_tiny_video_dataset

from guardian_ai.train import main


@pytest.fixture(scope="module")
def workspace(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Path]:
    root = tmp_path_factory.mktemp("cli-yolox")
    publish_tiny_video_dataset(root, clip_count=4)
    config_path = root / "smoke.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "name": "cli-yolox-smoke",
                "model": {"family": "yolox-tiny", "input_size": 64},
                "dataset": {
                    "registry_root": str(root / "registry"),
                    "name": "tiny-video-dataset",
                    "version": "1.0.0",
                    "format": "video",
                },
                "epochs": 2,
                "batch_size": 2,
                "early_stopping": {"enabled": False},
                "output_dir": str(root / "runs"),
            }
        ),
        encoding="utf-8",
    )
    return {"root": root, "config": config_path, "runs": root / "runs"}


def run_dir_of(workspace: dict[str, Path]) -> Path:
    runs = sorted(workspace["runs"].iterdir())
    assert runs, "no run directory created"
    return runs[-1]


def out(capsys: pytest.CaptureFixture) -> dict:
    return json.loads(capsys.readouterr().out)


def test_01_train(workspace: dict[str, Path], capsys: pytest.CaptureFixture) -> None:
    assert main(["train", "--config", str(workspace["config"])]) == 0
    payload = out(capsys)
    assert payload["status"] == "completed"
    assert payload["epochs_completed"] == 2


def test_02_evaluate(workspace: dict[str, Path], capsys: pytest.CaptureFixture) -> None:
    run = run_dir_of(workspace)
    assert main(["evaluate", "--run", str(run)]) == 0
    payload = out(capsys)
    assert "overall" in payload
    assert (run / "reports" / "evaluation.json").is_file()


def test_03_error_analysis(workspace: dict[str, Path], capsys: pytest.CaptureFixture) -> None:
    run = run_dir_of(workspace)
    assert main(["error-analysis", "--run", str(run), "--top-k", "3"]) == 0
    payload = out(capsys)
    assert payload["images_analyzed"] > 0
    assert (run / "reports" / "error-analysis.json").is_file()


def test_04_qualitative(workspace: dict[str, Path], capsys: pytest.CaptureFixture) -> None:
    run = run_dir_of(workspace)
    assert main(["qualitative", "--run", str(run), "--split", "train", "--count", "2"]) == 0
    payload = out(capsys)
    assert payload["written"] >= 1
    assert (run / "reports" / "qualitative").is_dir()


def test_05_export(workspace: dict[str, Path], capsys: pytest.CaptureFixture) -> None:
    run = run_dir_of(workspace)
    assert main(["export", "--run", str(run), "--version", "0.0.1"]) == 0
    payload = out(capsys)
    assert len(payload["compatibility"]) >= 7


def test_06_benchmark(workspace: dict[str, Path], capsys: pytest.CaptureFixture) -> None:
    run = run_dir_of(workspace)
    assert main(["benchmark", "--run", str(run), "--runs", "3"]) == 0
    payload = out(capsys)
    assert payload["latency_ms_mean"] > 0


def test_07_candidate_marks_status_without_touching_any_zoo(
    workspace: dict[str, Path], capsys: pytest.CaptureFixture
) -> None:
    run = run_dir_of(workspace)
    assert main(["candidate", "--run", str(run), "--notes", "cli smoke"]) == 0
    payload = out(capsys)
    assert payload["status"] == "candidate"
    record = json.loads((run / "experiment.json").read_text())
    assert record["candidate"] == {
        "status": "candidate",
        "not_production": True,
        "notes": "cli smoke",
    }


def test_08_qualitative_refuses_image_format_runs(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    from training_fixtures import publish_tiny_dataset

    root = tmp_path
    publish_tiny_dataset(root / "registry")
    config_path = root / "image-config.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "name": "image-format-run",
                "model": {"family": "tiny-ssd", "input_size": 64},
                "dataset": {"registry_root": str(root / "registry"), "name": "tiny-synthetic"},
                "epochs": 1,
                "batch_size": 4,
                "early_stopping": {"enabled": False},
                "output_dir": str(root / "runs"),
            }
        ),
        encoding="utf-8",
    )
    assert main(["train", "--config", str(config_path)]) == 0
    capsys.readouterr()
    run = sorted((root / "runs").iterdir())[-1]
    assert main(["qualitative", "--run", str(run)]) == 1
    assert "dataset.format: video" in capsys.readouterr().err


def test_09_coco_compare_refuses_without_evaluation(
    workspace: dict[str, Path], tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    config = yaml.safe_load(workspace["config"].read_text())
    config["output_dir"] = str(tmp_path / "runs")
    config["name"] = "fresh-for-coco-compare"
    fresh_config = tmp_path / "fresh.yaml"
    fresh_config.write_text(yaml.safe_dump(config), encoding="utf-8")
    assert main(["train", "--config", str(fresh_config)]) == 0
    capsys.readouterr()
    run = sorted((tmp_path / "runs").iterdir())[-1]
    code = main(
        [
            "coco-compare",
            "--run",
            str(run),
            "--zoo-root",
            str(tmp_path / "zoo"),
            "--edge-project-root",
            str(tmp_path / "no-edge"),
        ]
    )
    assert code == 1
    assert "run 'evaluate' first" in capsys.readouterr().err
