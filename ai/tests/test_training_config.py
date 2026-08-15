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
    assert config.scheduler.warmup_epochs == 0
    # Changed from "f1" after Sprint 20: F1 saturated at 1.0 by epoch 3
    # and the patience counter measured the ceiling, not the model.
    assert config.early_stopping.metric == "map50_95"
    assert config.early_stopping.min_delta == 0.0
    assert config.seed == 2026
    assert config.device == "cpu"


def test_warmup_epochs_is_configurable() -> None:
    config = config_from_dict({**VALID, "scheduler": {"name": "cosine", "warmup_epochs": 2}})
    assert config.scheduler.warmup_epochs == 2


def test_negative_warmup_epochs_is_rejected() -> None:
    with pytest.raises(TrainingConfigurationError, match="warmup_epochs"):
        config_from_dict({**VALID, "scheduler": {"warmup_epochs": -1}})


def test_warmup_epochs_must_be_less_than_epochs() -> None:
    with pytest.raises(TrainingConfigurationError, match="warmup_epochs"):
        config_from_dict({**VALID, "epochs": 5, "scheduler": {"warmup_epochs": 5}})


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


def test_registry_root_resolves_from_dataset_root_env_when_omitted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GUARDIAN_DATASET_ROOT", "/some/external/path")
    raw = dict(VALID)
    raw["dataset"] = {"name": "dummy-detection"}  # no registry_root
    config = config_from_dict(raw)
    assert config.dataset.registry_root == Path("/some/external/path/registry")


def test_registry_root_missing_and_no_env_var_fails_loudly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("GUARDIAN_DATASET_ROOT", raising=False)
    raw = dict(VALID)
    raw["dataset"] = {"name": "dummy-detection"}  # no registry_root
    with pytest.raises(TrainingConfigurationError, match="GUARDIAN_DATASET_ROOT"):
        config_from_dict(raw)


def test_explicit_registry_root_overrides_dataset_root_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GUARDIAN_DATASET_ROOT", "/should/not/be/used")
    config = config_from_dict(dict(VALID))  # VALID sets dataset.registry_root explicitly
    assert config.dataset.registry_root == Path("registry")


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
