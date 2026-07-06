"""Training config: one YAML, validated loudly."""

from __future__ import annotations

from pathlib import Path

import pytest

from guardian_ai.training.config import (
    TrainingConfig,
    config_from_dict,
    load_config,
)
from guardian_ai.training.errors import TrainingConfigurationError

VALID = {
    "name": "smoke",
    "model": {"family": "tiny-ssd", "input_size": 96},
    "dataset": {"registry_root": "registry", "name": "dummy-detection"},
    "epochs": 5,
    "batch_size": 8,
}


def test_minimal_config_gets_documented_defaults() -> None:
    config = config_from_dict(dict(VALID))
    assert config.optimizer.name == "adamw"
    assert config.scheduler.name == "cosine"
    assert config.early_stopping.metric == "f1"
    assert config.seed == 2026
    assert config.device == "cpu"


def test_yaml_roundtrip(tmp_path: Path) -> None:
    import yaml

    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(VALID), encoding="utf-8")
    config = load_config(path)
    assert config.name == "smoke"
    assert config.dataset.name == "dummy-detection"
    # to_dict must round-trip: the experiment record IS the recipe
    assert config_from_dict(config.to_dict()) == config


def test_unknown_top_level_key_is_rejected() -> None:
    with pytest.raises(TrainingConfigurationError, match="unknown config keys"):
        config_from_dict({**VALID, "epochz": 3})


@pytest.mark.parametrize(
    ("override", "message"),
    [
        ({"epochs": 0}, "epochs"),
        ({"batch_size": 0}, "batch_size"),
        ({"name": "  "}, "name"),
        ({"optimizer": {"name": "adamx"}}, "optimizer"),
        ({"optimizer": {"learning_rate": 0}}, "learning_rate"),
        ({"scheduler": {"name": "linear"}}, "scheduler"),
        ({"early_stopping": {"mode": "up"}}, "mode"),
        ({"early_stopping": {"patience": 0}}, "patience"),
        ({"augmentation": {"horizontal_flip": 1.5}}, "horizontal_flip"),
        ({"model": {"family": "tiny-ssd", "input_size": 8}}, "input_size"),
    ],
)
def test_invalid_values_fail_loudly(override: dict, message: str) -> None:
    with pytest.raises(TrainingConfigurationError, match=message):
        config_from_dict({**VALID, **override})


def test_missing_required_key() -> None:
    raw = dict(VALID)
    del raw["epochs"]
    with pytest.raises(TrainingConfigurationError, match="missing required key"):
        config_from_dict(raw)


def test_unknown_nested_knob_is_rejected() -> None:
    with pytest.raises(TrainingConfigurationError):
        config_from_dict({**VALID, "optimizer": {"lr": 0.1}})


def test_unreadable_and_invalid_yaml(tmp_path: Path) -> None:
    with pytest.raises(TrainingConfigurationError, match="cannot read"):
        load_config(tmp_path / "absent.yaml")
    bad = tmp_path / "bad.yaml"
    bad.write_text("just a string", encoding="utf-8")
    with pytest.raises(TrainingConfigurationError, match="mapping"):
        load_config(bad)


def test_config_is_immutable() -> None:
    config = config_from_dict(dict(VALID))
    with pytest.raises(AttributeError):
        config.epochs = 99  # type: ignore[misc]
    assert isinstance(config, TrainingConfig)
