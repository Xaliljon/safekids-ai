"""Label taxonomy and deterministic splitting."""

import pytest
from dataset_fixtures import make_record

from guardian_ai.datasets.errors import DatasetValidationError, TaxonomyError
from guardian_ai.datasets.splits import assign_split, split_records, validate_ratios
from guardian_ai.datasets.taxonomy import (
    GUARDIAN_TAXONOMY_V1,
    LabelDefinition,
    LabelTaxonomy,
)


class TestTaxonomy:
    def test_default_taxonomy_is_valid_and_identity_free(self) -> None:
        names = GUARDIAN_TAXONOMY_V1.label_names()
        assert names == {"person", "child", "adult"}
        assert GUARDIAN_TAXONOMY_V1.is_known("child")
        assert not GUARDIAN_TAXONOMY_V1.is_known("face")

    def test_rejects_duplicate_labels(self) -> None:
        with pytest.raises(TaxonomyError, match="duplicate"):
            LabelTaxonomy(
                name="t",
                version="1.0.0",
                labels=(LabelDefinition("person"), LabelDefinition("person")),
            )

    def test_rejects_empty_taxonomy(self) -> None:
        with pytest.raises(TaxonomyError):
            LabelTaxonomy(name="t", version="1.0.0", labels=())

    @pytest.mark.parametrize("name", ["Person", "with space", "", "1st"])
    def test_rejects_malformed_label_names(self, name: str) -> None:
        with pytest.raises(TaxonomyError):
            LabelDefinition(name)


class TestSplits:
    def test_assignment_is_deterministic(self) -> None:
        first = assign_split("images/000042.jpg")
        assert all(assign_split("images/000042.jpg") == first for _ in range(10))

    def test_growth_never_moves_existing_samples(self) -> None:
        original = {f"images/{i:05d}.jpg": assign_split(f"images/{i:05d}.jpg") for i in range(200)}
        # "Add" more samples — existing assignments are untouched by construction,
        # because assignment depends only on the sample's own path.
        for path, split in original.items():
            assert assign_split(path) == split

    def test_ratios_are_approximately_respected(self) -> None:
        records = [make_record(f"images/{i:05d}.jpg") for i in range(2000)]
        splits = split_records(records)
        assert set(splits) == {"train", "val", "test"}
        assert sum(len(records) for records in splits.values()) == 2000
        train_fraction = len(splits["train"]) / 2000
        assert 0.75 <= train_fraction <= 0.85

    def test_partition_is_disjoint_and_complete(self) -> None:
        records = [make_record(f"images/{i:05d}.jpg") for i in range(300)]
        splits = split_records(records)
        seen = [record.path for records in splits.values() for record in records]
        assert len(seen) == len(set(seen)) == 300

    @pytest.mark.parametrize(
        "ratios",
        [{}, {"train": 0.5}, {"train": 0.5, "val": 0.6}, {"train": -0.1, "val": 1.1}],
    )
    def test_invalid_ratios_are_rejected(self, ratios: dict[str, float]) -> None:
        with pytest.raises(DatasetValidationError):
            validate_ratios(ratios)
