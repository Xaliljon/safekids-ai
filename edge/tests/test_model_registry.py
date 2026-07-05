"""Filesystem model registry: resolution, versions, and artifact verification."""

import json
from pathlib import Path

import pytest
from conftest import install_model

from guardian_edge.domain.errors import ModelRegistryError
from guardian_edge.infrastructure.inference.registry import FileSystemModelRegistry


def test_lists_all_valid_models(tmp_path: Path) -> None:
    install_model(tmp_path, "model-a", version="1.0.0")
    install_model(tmp_path, "model-b", version="0.2.0")
    names = {m.model.name for m in FileSystemModelRegistry(tmp_path).list_models()}
    assert names == {"model-a", "model-b"}


def test_listing_skips_broken_manifests_but_keeps_valid_ones(tmp_path: Path) -> None:
    install_model(tmp_path, "good-model")
    broken = tmp_path / "broken-model" / "1.0.0"
    broken.mkdir(parents=True)
    (broken / "manifest.json").write_text("{not json", encoding="utf-8")
    manifests = FileSystemModelRegistry(tmp_path).list_models()
    assert [m.model.name for m in manifests] == ["good-model"]


def test_empty_or_missing_root_lists_nothing(tmp_path: Path) -> None:
    assert FileSystemModelRegistry(tmp_path / "nope").list_models() == []


def test_get_resolves_exact_version(tmp_path: Path) -> None:
    install_model(tmp_path, "model-a", version="1.0.0")
    install_model(tmp_path, "model-a", version="1.1.0")
    registered = FileSystemModelRegistry(tmp_path).get("model-a", "1.0.0")
    assert registered.manifest.model.version == "1.0.0"
    assert registered.path.is_file()


def test_get_without_version_resolves_latest(tmp_path: Path) -> None:
    install_model(tmp_path, "model-a", version="1.2.0")
    install_model(tmp_path, "model-a", version="1.10.0")  # numeric, not lexicographic
    install_model(tmp_path, "model-a", version="0.9.9")
    registered = FileSystemModelRegistry(tmp_path).get("model-a")
    assert registered.manifest.model.version == "1.10.0"


def test_unknown_model_raises(tmp_path: Path) -> None:
    with pytest.raises(ModelRegistryError, match="unknown model"):
        FileSystemModelRegistry(tmp_path).get("ghost")


def test_unknown_version_raises(tmp_path: Path) -> None:
    install_model(tmp_path, "model-a", version="1.0.0")
    with pytest.raises(ModelRegistryError, match="no version"):
        FileSystemModelRegistry(tmp_path).get("model-a", "9.9.9")


def test_missing_artifact_raises(tmp_path: Path) -> None:
    version_dir = install_model(tmp_path, "model-a")
    (version_dir / "model.onnx").unlink()
    with pytest.raises(ModelRegistryError, match="artifact missing"):
        FileSystemModelRegistry(tmp_path).get("model-a")


def test_checksum_mismatch_refuses_to_load(tmp_path: Path) -> None:
    version_dir = install_model(tmp_path, "model-a", with_checksum=False)
    manifest = json.loads((version_dir / "manifest.json").read_text(encoding="utf-8"))
    manifest["sha256"] = "0" * 64
    (version_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ModelRegistryError, match="checksum mismatch"):
        FileSystemModelRegistry(tmp_path).get("model-a")


def test_manifest_name_must_match_directory(tmp_path: Path) -> None:
    install_model(tmp_path, "model-a", manifest_overrides={"name": "impostor"})
    with pytest.raises(ModelRegistryError, match="declares model"):
        FileSystemModelRegistry(tmp_path).get("model-a")
