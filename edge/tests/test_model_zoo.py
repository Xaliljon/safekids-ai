"""Model zoo: validated installs, activation, rollback, OTA properties."""

from pathlib import Path

import pytest
from conftest import build_bundle

from guardian_edge.domain.errors import (
    ModelCompatibilityError,
    ModelInstallError,
    ModelLicenseError,
    ModelRegistryError,
)
from guardian_edge.infrastructure.inference.registry import FileSystemModelRegistry
from guardian_edge.infrastructure.inference.zoo import STAGING_DIR_NAME, FileSystemModelZoo


@pytest.fixture
def root(tmp_path: Path) -> Path:
    return tmp_path / "models"


@pytest.fixture
def zoo(root: Path) -> FileSystemModelZoo:
    root.mkdir()
    return FileSystemModelZoo(root)


def bundle(tmp_path: Path, version: str = "1.0.0", **kwargs: object) -> Path:
    return build_bundle(tmp_path / f"bundle-{version}", version=version, **kwargs)  # type: ignore[arg-type]


class TestInstall:
    def test_installs_a_valid_bundle(
        self, zoo: FileSystemModelZoo, root: Path, tmp_path: Path
    ) -> None:
        manifest = zoo.install(bundle(tmp_path))
        assert manifest.model.name == "bundled-model"
        assert (root / "bundled-model" / "1.0.0" / "manifest.json").is_file()
        assert (root / "bundled-model" / "1.0.0" / "model.onnx").is_file()
        assert zoo.versions("bundled-model") == ["1.0.0"]
        registered = FileSystemModelRegistry(root).get("bundled-model")
        assert registered.manifest.model.version == "1.0.0"

    def test_versions_are_immutable(self, zoo: FileSystemModelZoo, tmp_path: Path) -> None:
        zoo.install(bundle(tmp_path))
        with pytest.raises(ModelInstallError, match="immutable"):
            zoo.install(build_bundle(tmp_path / "again", version="1.0.0"))

    def test_missing_checksum_is_refused(self, zoo: FileSystemModelZoo, tmp_path: Path) -> None:
        with pytest.raises(ModelInstallError, match="no sha256"):
            zoo.install(bundle(tmp_path, with_checksum=False))

    def test_tampered_artifact_is_refused_and_leaves_no_trace(
        self, zoo: FileSystemModelZoo, root: Path, tmp_path: Path
    ) -> None:
        with pytest.raises(ModelInstallError, match="corrupt or tampered"):
            zoo.install(bundle(tmp_path, corrupt_after_hashing=True))
        assert not (root / "bundled-model").exists(), "refused install must leave no trace"
        staging = root / STAGING_DIR_NAME
        assert not staging.exists() or not any(staging.iterdir())

    def test_disallowed_license_is_refused(self, zoo: FileSystemModelZoo, tmp_path: Path) -> None:
        with pytest.raises(ModelLicenseError, match="AGPL-3.0"):
            zoo.install(bundle(tmp_path, license_id="AGPL-3.0"))

    def test_undeclared_license_is_refused(self, zoo: FileSystemModelZoo, tmp_path: Path) -> None:
        with pytest.raises(ModelLicenseError, match="no license"):
            zoo.install(bundle(tmp_path, license_id=None))

    def test_incompatible_model_is_refused(self, zoo: FileSystemModelZoo, tmp_path: Path) -> None:
        too_new = bundle(tmp_path, compatibility={"min_edge_version": "99.0.0"})
        with pytest.raises(ModelCompatibilityError, match="99.0.0"):
            zoo.install(too_new)

    def test_missing_artifact_is_refused(self, zoo: FileSystemModelZoo, tmp_path: Path) -> None:
        bundle_dir = bundle(tmp_path)
        (bundle_dir / "model.onnx").unlink()
        with pytest.raises(ModelInstallError, match="missing artifact"):
            zoo.install(bundle_dir)

    def test_install_with_activate_sets_the_pointer(
        self, zoo: FileSystemModelZoo, tmp_path: Path
    ) -> None:
        zoo.install(bundle(tmp_path), activate=True)
        assert zoo.active_version("bundled-model") == "1.0.0"


class TestActivationAndRollback:
    def test_registry_resolves_active_version_not_latest(
        self, zoo: FileSystemModelZoo, root: Path, tmp_path: Path
    ) -> None:
        zoo.install(bundle(tmp_path, version="1.0.0"), activate=True)
        zoo.install(bundle(tmp_path, version="2.0.0"))  # newer, but NOT activated
        registered = FileSystemModelRegistry(root).get("bundled-model")
        assert registered.manifest.model.version == "1.0.0", "active pointer must win"

    def test_activation_switches_and_remembers_previous(
        self, zoo: FileSystemModelZoo, tmp_path: Path
    ) -> None:
        zoo.install(bundle(tmp_path, version="1.0.0"), activate=True)
        zoo.install(bundle(tmp_path, version="1.1.0"), activate=True)
        assert zoo.active_version("bundled-model") == "1.1.0"
        rolled_back_to = zoo.rollback("bundled-model")
        assert rolled_back_to == "1.0.0"
        assert zoo.active_version("bundled-model") == "1.0.0"

    def test_rollback_is_reversible(self, zoo: FileSystemModelZoo, tmp_path: Path) -> None:
        zoo.install(bundle(tmp_path, version="1.0.0"), activate=True)
        zoo.install(bundle(tmp_path, version="1.1.0"), activate=True)
        zoo.rollback("bundled-model")
        assert zoo.rollback("bundled-model") == "1.1.0", "roll forward again"

    def test_rollback_without_history_fails(self, zoo: FileSystemModelZoo, tmp_path: Path) -> None:
        zoo.install(bundle(tmp_path), activate=True)
        with pytest.raises(ModelInstallError, match="no previous version"):
            zoo.rollback("bundled-model")

    def test_activating_unknown_version_fails(
        self, zoo: FileSystemModelZoo, tmp_path: Path
    ) -> None:
        zoo.install(bundle(tmp_path))
        with pytest.raises(ModelRegistryError):
            zoo.activate("bundled-model", "9.9.9")

    def test_activation_is_idempotent(self, zoo: FileSystemModelZoo, tmp_path: Path) -> None:
        zoo.install(bundle(tmp_path, version="1.0.0"), activate=True)
        zoo.install(bundle(tmp_path, version="1.1.0"), activate=True)
        zoo.activate("bundled-model", "1.1.0")  # re-activating the active version
        assert zoo.rollback("bundled-model") == "1.0.0", "previous must be preserved"


class TestRemoval:
    def test_removes_inactive_version(self, zoo: FileSystemModelZoo, tmp_path: Path) -> None:
        zoo.install(bundle(tmp_path, version="1.0.0"))
        zoo.install(bundle(tmp_path, version="1.1.0"), activate=True)
        zoo.remove("bundled-model", "1.0.0")
        assert zoo.versions("bundled-model") == ["1.1.0"]

    def test_refuses_to_remove_the_active_version(
        self, zoo: FileSystemModelZoo, tmp_path: Path
    ) -> None:
        zoo.install(bundle(tmp_path), activate=True)
        with pytest.raises(ModelInstallError, match="active"):
            zoo.remove("bundled-model", "1.0.0")

    def test_removing_the_rollback_target_clears_history(
        self, zoo: FileSystemModelZoo, tmp_path: Path
    ) -> None:
        zoo.install(bundle(tmp_path, version="1.0.0"), activate=True)
        zoo.install(bundle(tmp_path, version="1.1.0"), activate=True)
        zoo.remove("bundled-model", "1.0.0")
        with pytest.raises(ModelInstallError, match="no previous version"):
            zoo.rollback("bundled-model")

    def test_removing_unknown_version_fails(self, zoo: FileSystemModelZoo, tmp_path: Path) -> None:
        zoo.install(bundle(tmp_path))
        with pytest.raises(ModelRegistryError, match="no version"):
            zoo.remove("bundled-model", "3.0.0")


class TestOtaProperties:
    def test_versions_are_sorted_semantically(
        self, zoo: FileSystemModelZoo, tmp_path: Path
    ) -> None:
        for version in ("1.10.0", "1.2.0", "1.0.0"):
            zoo.install(bundle(tmp_path, version=version))
        assert zoo.versions("bundled-model") == ["1.0.0", "1.2.0", "1.10.0"]

    def test_stale_staging_debris_is_cleaned_on_startup(self, root: Path) -> None:
        crashed = root / STAGING_DIR_NAME / "bundled-model-1.0.0-deadbeef"
        crashed.mkdir(parents=True)
        (crashed / "model.onnx").write_bytes(b"partial download")
        FileSystemModelZoo(root)  # startup recovers
        assert not any((root / STAGING_DIR_NAME).iterdir())

    def test_staged_debris_never_appears_in_the_registry(self, root: Path, tmp_path: Path) -> None:
        zoo = FileSystemModelZoo(root)
        zoo.install(bundle(tmp_path))
        crashed = root / STAGING_DIR_NAME / "other-model-1.0.0-cafe"
        crashed.mkdir(parents=True)
        build_bundle(crashed, name="other-model")
        names = {m.model.name for m in FileSystemModelRegistry(root).list_models()}
        assert names == {"bundled-model"}
