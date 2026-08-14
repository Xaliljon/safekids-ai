"""ADR-0005 governance: licence, usage, ethics review, retention, withdrawal.

Every test here is a refusal. That is the point — this subsystem's job is
to say no at publish or promotion time rather than years later in front of
a customer or a parent.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from guardian_ai.datasets.errors import (
    DatasetPublishError,
    DatasetRegistryError,
    DatasetValidationError,
)
from guardian_ai.datasets.licensing import DatasetUsage, check_dataset_license
from guardian_ai.datasets.lifecycle import (
    DatasetLifecycle,
    Tombstone,
    load_tombstone,
    save_tombstone,
)
from guardian_ai.datasets.manifest import DATASET_MANIFEST_NAME, load_manifest
from guardian_ai.datasets.registry import FileSystemDatasetRegistry
from guardian_ai.datasets.taxonomy import LabelDefinition, LabelTaxonomy

_NOW = "2026-08-15T10:00:00+00:00"


# --------------------------------------------------------------- fixtures


@pytest.fixture
def taxonomy() -> LabelTaxonomy:
    return LabelTaxonomy(
        name="guardian-safety",
        version="1.0.0",
        labels=(LabelDefinition(name="person"),),
    )


def _bundle(
    tmp_path: Path,
    *,
    name: str = "fall-detection",
    version: str = "1.0.0",
    license_id: str = "Apache-2.0",
    usage: str | None = None,
    contains_minors: bool = False,
    review_reference: str = "",
    retention_until: str = "",
) -> Path:
    bundle = tmp_path / f"bundle-{name}-{version}"
    (bundle / "annotations").mkdir(parents=True)
    (bundle / "annotations" / "train.jsonl").write_text(
        json.dumps(
            {
                "path": "clips/a/frame_000001.jpg",
                "width": 640,
                "height": 480,
                "annotations": [
                    {
                        "label": "person",
                        "box": {"x": 0.1, "y": 0.2, "width": 0.3, "height": 0.4},
                    }
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    manifest = {
        "name": name,
        "version": version,
        "description": "governance fixture",
        "taxonomy": {"name": "guardian-safety", "version": "1.0.0"},
        "created_utc": _NOW,
        "provenance": {
            "collected_by": "Guardian AI",
            "consent_reference": "agreement-2026-001",
            "notes": "",
        },
        "privacy": {
            "contains_minors": contains_minors,
            "anonymized": False,
            "review_reference": review_reference,
            "retention_until": retention_until,
        },
        "splits": {"train": {"file": "train.jsonl"}},
        "license": license_id,
    }
    if usage is not None:
        manifest["usage"] = usage
    (bundle / DATASET_MANIFEST_NAME).write_text(json.dumps(manifest), encoding="utf-8")
    return bundle


# ------------------------------------------------------- licence and usage


def test_commercial_license_passes() -> None:
    check_dataset_license("Apache-2.0", DatasetUsage.TRAINING, "d")


def test_unknown_license_blocks_publication() -> None:
    with pytest.raises(DatasetValidationError, match="maps to no known term"):
        check_dataset_license("SomeLab-Terms-v2", DatasetUsage.TRAINING, "d")


def test_empty_license_is_not_permission() -> None:
    with pytest.raises(DatasetValidationError, match="no license declared"):
        check_dataset_license("   ", DatasetUsage.TRAINING, "d")


@pytest.mark.parametrize(
    "license_id",
    ["CC-BY-NC-SA-4.0", "CC-BY-NC-4.0", "Research-Only", "SomeUniversity-NonCommercial"],
)
def test_non_commercial_license_refused_for_training(license_id: str) -> None:
    """OmniFall is the concrete case: CC-BY-NC-SA, fits the problem, unusable."""
    with pytest.raises(DatasetValidationError, match="does not permit"):
        check_dataset_license(license_id, DatasetUsage.TRAINING, "omnifall")


@pytest.mark.parametrize("license_id", ["CC-BY-NC-SA-4.0", "Research-Only"])
def test_non_commercial_license_allowed_for_evaluation(license_id: str) -> None:
    """Research corpora stay usable as instruments — Le2i and UR Fall are
    exactly this case, and blocking them outright would block measurement."""
    check_dataset_license(license_id, DatasetUsage.EVALUATION_ONLY, "urfall")


def test_publish_refuses_research_license_for_training(
    tmp_path: Path, taxonomy: LabelTaxonomy
) -> None:
    registry = FileSystemDatasetRegistry(tmp_path / "registry")
    bundle = _bundle(tmp_path, license_id="Research-Only")
    with pytest.raises(DatasetPublishError, match="does not permit"):
        registry.publish(bundle, taxonomy)
    assert not (tmp_path / "registry" / "fall-detection").exists()


def test_publish_accepts_research_license_as_evaluation_only(
    tmp_path: Path, taxonomy: LabelTaxonomy
) -> None:
    registry = FileSystemDatasetRegistry(tmp_path / "registry")
    bundle = _bundle(tmp_path, license_id="Research-Only", usage="evaluation-only")
    manifest = registry.publish(bundle, taxonomy)
    assert manifest.usage is DatasetUsage.EVALUATION_ONLY
    assert registry.get("fall-detection").manifest.usage is DatasetUsage.EVALUATION_ONLY


def test_usage_defaults_to_training_for_manifests_without_it(tmp_path: Path) -> None:
    """Manifests written before ADR-0005 keep loading unchanged."""
    bundle = _bundle(tmp_path)
    assert load_manifest(bundle / DATASET_MANIFEST_NAME).usage is DatasetUsage.TRAINING


# ------------------------------------------------- minors: review, retention


def test_minors_without_resolver_cannot_be_published(
    tmp_path: Path, taxonomy: LabelTaxonomy
) -> None:
    """A registry that cannot verify a review cannot publish children's data.

    This is the default posture, deliberately: wiring a resolver is an
    explicit act (ADR-0005 §3).
    """
    registry = FileSystemDatasetRegistry(tmp_path / "registry")
    bundle = _bundle(
        tmp_path,
        contains_minors=True,
        review_reference="ethics-2026-004",
        retention_until="2028-08-15",
    )
    with pytest.raises(DatasetPublishError, match="no review resolver"):
        registry.publish(bundle, taxonomy)


def test_minors_with_unresolvable_review_refused(tmp_path: Path, taxonomy: LabelTaxonomy) -> None:
    registry = FileSystemDatasetRegistry(tmp_path / "registry", review_resolver=lambda _: False)
    bundle = _bundle(
        tmp_path,
        contains_minors=True,
        review_reference="ethics-2026-004",
        retention_until="2028-08-15",
    )
    with pytest.raises(DatasetPublishError, match="resolves to nothing"):
        registry.publish(bundle, taxonomy)


def test_minors_without_retention_refused(tmp_path: Path, taxonomy: LabelTaxonomy) -> None:
    registry = FileSystemDatasetRegistry(tmp_path / "registry", review_resolver=lambda _: True)
    bundle = _bundle(tmp_path, contains_minors=True, review_reference="ethics-2026-004")
    with pytest.raises(DatasetPublishError, match="retention_until"):
        registry.publish(bundle, taxonomy)


def test_minors_publishable_with_resolvable_review_and_retention(
    tmp_path: Path, taxonomy: LabelTaxonomy
) -> None:
    seen: list[str] = []

    def resolver(reference: str) -> bool:
        seen.append(reference)
        return True

    registry = FileSystemDatasetRegistry(tmp_path / "registry", review_resolver=resolver)
    bundle = _bundle(
        tmp_path,
        contains_minors=True,
        review_reference="ethics-2026-004",
        retention_until="2028-08-15",
    )
    manifest = registry.publish(bundle, taxonomy)
    assert seen == ["ethics-2026-004"]
    assert manifest.privacy.retention_until == "2028-08-15"


def test_adults_need_neither_review_nor_retention(tmp_path: Path, taxonomy: LabelTaxonomy) -> None:
    """The gate governs minors. Adult research corpora stay unblocked
    (ADR-0005 scope) — this is the test that keeps it that way."""
    registry = FileSystemDatasetRegistry(tmp_path / "registry")
    registry.publish(_bundle(tmp_path, license_id="CC-BY-4.0"), taxonomy)


# ------------------------------------------------------------- withdrawal


def test_tombstone_requires_a_named_person() -> None:
    with pytest.raises(DatasetValidationError, match="recorded_by"):
        Tombstone(
            lifecycle=DatasetLifecycle.WITHDRAWN,
            reason="guardian withdrew consent",
            recorded_utc=_NOW,
            recorded_by="  ",
        )


def test_tombstone_cannot_record_active() -> None:
    with pytest.raises(DatasetValidationError, match="cannot record ACTIVE"):
        Tombstone(
            lifecycle=DatasetLifecycle.ACTIVE,
            reason="r",
            recorded_utc=_NOW,
            recorded_by="Reviewer",
        )


def test_withdrawn_version_refuses_to_load(tmp_path: Path, taxonomy: LabelTaxonomy) -> None:
    registry = FileSystemDatasetRegistry(tmp_path / "registry")
    registry.publish(_bundle(tmp_path), taxonomy)
    registry.withdraw(
        "fall-detection",
        "1.0.0",
        reason="guardian of subject 14 withdrew consent",
        recorded_by="Data Protection Lead",
        recorded_utc=_NOW,
    )
    with pytest.raises(DatasetRegistryError, match="tombstoned as withdrawn"):
        registry.get("fall-detection", "1.0.0")


def test_withdrawn_version_still_readable_for_audit(
    tmp_path: Path, taxonomy: LabelTaxonomy
) -> None:
    """Consent withdrawal revokes the licence to train, not the record of
    what a deployed model learned from."""
    registry = FileSystemDatasetRegistry(tmp_path / "registry")
    registry.publish(_bundle(tmp_path), taxonomy)
    registry.withdraw(
        "fall-detection",
        "1.0.0",
        reason="guardian withdrew consent",
        recorded_by="Data Protection Lead",
        recorded_utc=_NOW,
        superseded_by="1.1.0",
    )
    audited = registry.get_for_audit("fall-detection", "1.0.0")
    assert audited.manifest.name == "fall-detection"
    assert audited.tombstone is not None
    assert audited.tombstone.superseded_by == "1.1.0"


def test_latest_skips_withdrawn_and_resolves_the_replacement(
    tmp_path: Path, taxonomy: LabelTaxonomy
) -> None:
    """Withdrawal publishes a replacement; that replacement is what
    "latest" must mean, or every caller breaks on the day consent changes."""
    registry = FileSystemDatasetRegistry(tmp_path / "registry")
    registry.publish(_bundle(tmp_path, version="1.0.0"), taxonomy)
    registry.publish(_bundle(tmp_path, version="1.1.0"), taxonomy)
    registry.withdraw(
        "fall-detection",
        "1.0.0",
        reason="guardian withdrew consent",
        recorded_by="Data Protection Lead",
        recorded_utc=_NOW,
        superseded_by="1.1.0",
    )
    assert registry.get("fall-detection").manifest.version == "1.1.0"


def test_all_versions_withdrawn_leaves_nothing_loadable(
    tmp_path: Path, taxonomy: LabelTaxonomy
) -> None:
    registry = FileSystemDatasetRegistry(tmp_path / "registry")
    registry.publish(_bundle(tmp_path), taxonomy)
    registry.withdraw(
        "fall-detection",
        "1.0.0",
        reason="guardian withdrew consent",
        recorded_by="Data Protection Lead",
        recorded_utc=_NOW,
    )
    with pytest.raises(DatasetRegistryError, match="every one is tombstoned"):
        registry.get("fall-detection")


def test_withdrawal_record_is_never_rewritten(tmp_path: Path, taxonomy: LabelTaxonomy) -> None:
    registry = FileSystemDatasetRegistry(tmp_path / "registry")
    registry.publish(_bundle(tmp_path), taxonomy)
    registry.withdraw(
        "fall-detection",
        "1.0.0",
        reason="guardian withdrew consent",
        recorded_by="Data Protection Lead",
        recorded_utc=_NOW,
    )
    with pytest.raises(DatasetRegistryError, match="already tombstoned"):
        registry.withdraw(
            "fall-detection",
            "1.0.0",
            reason="something more convenient",
            recorded_by="Someone Else",
            recorded_utc=_NOW,
        )


def test_expiry_uses_the_same_mechanism(tmp_path: Path, taxonomy: LabelTaxonomy) -> None:
    registry = FileSystemDatasetRegistry(tmp_path / "registry")
    registry.publish(_bundle(tmp_path), taxonomy)
    registry.expire(
        "fall-detection",
        "1.0.0",
        reason="retention period ended 2028-08-15",
        recorded_by="Data Protection Lead",
        recorded_utc=_NOW,
    )
    tombstone = registry.tombstone_of("fall-detection", "1.0.0")
    assert tombstone is not None
    assert tombstone.lifecycle is DatasetLifecycle.EXPIRED


def test_active_version_has_no_tombstone(tmp_path: Path, taxonomy: LabelTaxonomy) -> None:
    registry = FileSystemDatasetRegistry(tmp_path / "registry")
    registry.publish(_bundle(tmp_path), taxonomy)
    assert registry.tombstone_of("fall-detection", "1.0.0") is None
    assert registry.get("fall-detection", "1.0.0").tombstone is None


def test_tombstone_roundtrips(tmp_path: Path) -> None:
    version_dir = tmp_path / "v"
    version_dir.mkdir()
    original = Tombstone(
        lifecycle=DatasetLifecycle.WITHDRAWN,
        reason="guardian withdrew consent",
        recorded_utc=_NOW,
        recorded_by="Data Protection Lead",
        superseded_by="1.1.0",
    )
    save_tombstone(version_dir, original)
    assert load_tombstone(version_dir) == original
