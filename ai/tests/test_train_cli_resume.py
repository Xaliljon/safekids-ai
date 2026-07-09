"""CLI auto-resume (Sprint 20.1): re-running `train` continues an
unfinished run instead of starting over, so a disconnected Colab can just
Run All again. Kept separate from test_train_cli.py's ordered, shared
workspace so these get their own clean run directories."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from training_fixtures import publish_tiny_dataset

from guardian_ai.train import _find_latest_run, main


@pytest.fixture(scope="module")
def registry(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("resume-registry") / "registry"
    publish_tiny_dataset(root)
    return root


def _write_config(path: Path, registry: Path, name: str, epochs: int) -> Path:
    path.write_text(
        yaml.safe_dump(
            {
                "name": name,
                "model": {"family": "tiny-ssd", "input_size": 64},
                "dataset": {"registry_root": str(registry), "name": "tiny-synthetic"},
                "epochs": epochs,
                "batch_size": 4,
                "early_stopping": {"enabled": False},
                "output_dir": str(path.parent / "unused"),  # always overridden by --output-dir
            }
        ),
        encoding="utf-8",
    )
    return path


def test_auto_resume_starts_fresh_when_no_prior_run(
    registry: Path, tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    runs = tmp_path / "runs"
    config = _write_config(tmp_path / "c.yaml", registry, "fresh-run", epochs=2)

    assert main(["train", "--config", str(config), "--auto-resume", "--output-dir", str(runs)]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "completed"
    assert payload["epochs_completed"] == 2
    assert len([d for d in runs.iterdir() if d.is_dir()]) == 1


def test_auto_resume_leaves_a_completed_run_untouched(
    registry: Path, tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    runs = tmp_path / "runs"
    config = _write_config(tmp_path / "c.yaml", registry, "done-run", epochs=2)

    main(["train", "--config", str(config), "--auto-resume", "--output-dir", str(runs)])
    capsys.readouterr()
    # second Run All: the completed run is detected, not retrained, not duplicated
    assert main(["train", "--config", str(config), "--auto-resume", "--output-dir", str(runs)]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "completed"
    assert "already complete" in payload["note"]
    assert len([d for d in runs.iterdir() if d.is_dir()]) == 1


def test_auto_resume_continues_an_unfinished_run(
    registry: Path, tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    from guardian_ai.training.experiment import Experiment

    runs = tmp_path / "runs"
    short = _write_config(tmp_path / "short.yaml", registry, "long-run", epochs=2)

    main(["train", "--config", str(short), "--auto-resume", "--output-dir", str(runs)])
    capsys.readouterr()

    # simulate an interrupted run: the checkpoint is intact but the record is
    # not marked completed (exactly the state a mid-training disconnect leaves)
    run_dir = _find_latest_run(runs, "long-run")
    assert run_dir is not None
    interrupted = Experiment.load(run_dir)
    interrupted.record["status"] = "training"
    interrupted.save()

    longer = _write_config(tmp_path / "long.yaml", registry, "long-run", epochs=4)
    assert main(["train", "--config", str(longer), "--auto-resume", "--output-dir", str(runs)]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert "auto-resume" in payload["note"]
    assert payload["epochs_completed"] == 4
    assert len([d for d in runs.iterdir() if d.is_dir()]) == 1  # same run, not a new one


def test_find_latest_run_matches_by_name(registry: Path, tmp_path: Path) -> None:
    runs = tmp_path / "runs"
    _write_config(tmp_path / "c.yaml", registry, "named-run", epochs=1)
    main(["train", "--config", str(tmp_path / "c.yaml"), "--output-dir", str(runs)])

    assert _find_latest_run(runs, "named-run") is not None
    assert _find_latest_run(runs, "no-such-experiment") is None
    assert _find_latest_run(tmp_path / "does-not-exist", "named-run") is None


def test_output_dir_override_redirects_the_run(
    registry: Path, tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    override = tmp_path / "elsewhere"
    config = _write_config(tmp_path / "c.yaml", registry, "redirect-run", epochs=1)

    assert main(["train", "--config", str(config), "--output-dir", str(override)]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert str(override) in payload["run_dir"]
    assert not (tmp_path / "unused").exists()  # the config's own output_dir was not used
