"""CLI end-to-end: the full mandated workflow on a real (synthetic) dataset.

Dataset -> train -> evaluate -> export -> benchmark -> report -> compare
-> promote, all through ``python -m guardian_ai.train`` argument parsing.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from training_fixtures import publish_tiny_dataset

from guardian_ai.train import main


@pytest.fixture(scope="module")
def workspace(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Path]:
    root = tmp_path_factory.mktemp("cli")
    registry = root / "registry"
    publish_tiny_dataset(registry)
    config_path = root / "smoke.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "name": "cli-smoke",
                "model": {"family": "tiny-ssd", "input_size": 64},
                "dataset": {"registry_root": str(registry), "name": "tiny-synthetic"},
                "epochs": 2,
                "batch_size": 4,
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


def test_01_train(workspace: dict[str, Path], capsys: pytest.CaptureFixture) -> None:
    assert main(["train", "--config", str(workspace["config"])]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "completed"
    assert payload["epochs_completed"] == 2
    assert (run_dir_of(workspace) / "experiment.json").is_file()


def test_02_resume_continues(workspace: dict[str, Path], capsys: pytest.CaptureFixture) -> None:
    run = run_dir_of(workspace)
    # same config, same epochs -> resume verifies state loads and finishes
    assert main(["resume", "--run", str(run)]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "completed"


def test_03_evaluate(workspace: dict[str, Path], capsys: pytest.CaptureFixture) -> None:
    run = run_dir_of(workspace)
    assert main(["evaluate", "--run", str(run)]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["split"] == "test"
    evaluation = json.loads((run / "reports" / "evaluation.json").read_text())
    assert "confusion_matrix" in evaluation


def test_04_export_with_manifest_and_compat(
    workspace: dict[str, Path], capsys: pytest.CaptureFixture
) -> None:
    run = run_dir_of(workspace)
    assert main(["export", "--run", str(run), "--version", "0.0.1"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert len(payload["compatibility"]) >= 7
    manifest = json.loads((run / "export" / "manifest.json").read_text())
    assert manifest["name"] == "tiny-ssd"
    assert manifest["version"] == "0.0.1"
    assert manifest["metadata"]["training"]["dataset"]["name"] == "tiny-synthetic"
    record = json.loads((run / "experiment.json").read_text())
    assert record["checksums"]["model.onnx"] == manifest["sha256"]


def test_05_benchmark(workspace: dict[str, Path], capsys: pytest.CaptureFixture) -> None:
    run = run_dir_of(workspace)
    assert main(["benchmark", "--run", str(run), "--runs", "5"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["latency_ms_mean"] > 0


def test_06_report(workspace: dict[str, Path], capsys: pytest.CaptureFixture) -> None:
    run = run_dir_of(workspace)
    assert main(["report", "--run", str(run)]) == 0
    reports = run / "reports"
    for name in ("confusion_matrix.png", "pr_curve.png", "loss_curve.png", "summary.pdf"):
        assert (reports / name).is_file()


def test_07_compare_self_promotes(
    workspace: dict[str, Path], capsys: pytest.CaptureFixture
) -> None:
    run = run_dir_of(workspace)
    code = main(["compare", "--candidate", str(run), "--baseline", str(run), "--runs", "5"])
    payload = json.loads(capsys.readouterr().out)
    assert payload["verdict"] == "PROMOTE"
    assert code == 0
    assert (run / "comparison.json").is_file()


def test_08_promote_into_zoo(workspace: dict[str, Path], capsys: pytest.CaptureFixture) -> None:
    run = run_dir_of(workspace)
    zoo = workspace["root"] / "zoo"
    assert main(["promote", "--run", str(run), "--zoo", str(zoo), "--approved-by", "Reviewer"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["approved_by"] == "Reviewer"
    assert (zoo / "tiny-ssd" / "0.0.1" / "model.onnx").is_file()
    assert (zoo / "tiny-ssd" / "0.0.1" / "manifest.json").is_file()


def test_09_errors_exit_nonzero(workspace: dict[str, Path], capsys: pytest.CaptureFixture) -> None:
    missing = workspace["root"] / "nowhere"
    assert main(["evaluate", "--run", str(missing)]) == 1
    assert "error:" in capsys.readouterr().err


def test_10_report_before_evaluate_fails(
    workspace: dict[str, Path], tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    # fresh run with no evaluation.json
    config = yaml.safe_load(workspace["config"].read_text())
    config["output_dir"] = str(tmp_path / "runs")
    config["epochs"] = 1
    fresh = tmp_path / "fresh.yaml"
    fresh.write_text(yaml.safe_dump(config), encoding="utf-8")
    assert main(["train", "--config", str(fresh)]) == 0
    capsys.readouterr()
    run = sorted((tmp_path / "runs").iterdir())[-1]
    assert main(["report", "--run", str(run)]) == 1
    assert "evaluate" in capsys.readouterr().err
