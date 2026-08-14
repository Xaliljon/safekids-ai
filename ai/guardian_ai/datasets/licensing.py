"""Dataset licence gate — the symmetric twin of the model zoo's (ADR-0005 §5).

ADR-0003/0009 made the model zoo refuse AGPL structurally, so no engineer
can accidentally ship a weight file Guardian has no right to ship. Data
carries the same risk and had no such gate: a research-only corpus trains a
model just as well as a permissive one, and the problem surfaces years later
in front of a customer.

Two questions are asked here, and they are deliberately separate:

*What licence is it?* — a licence that cannot be mapped to a known term
blocks publication. Silence is not permission, and a field that defaults to
"Proprietary-GuardianAI" is not a declaration.

*What may it be used for?* — this is where reality did not fit the ADR's
first draft. Guardian's own importers describe Le2i as "research use" and UR
Fall as "free for research use". Training a model that ships in a commercial
product is exactly the use those terms withhold. But *measuring* a model on
them is not: a held-out research corpus answering "does this generalize
beyond four rooms" is a laboratory instrument, not a shipped asset.

So research-licensed data is publishable as ``EVALUATION_ONLY``. It may be
loaded, scored against, and reported on. What it may not do is train
anything that reaches the zoo — and that refusal lives in the promotion
gate, next to the withdrawal refusal, because promotion is the moment a
licence question becomes a shipping question.
"""

from __future__ import annotations

from enum import Enum

from guardian_ai.datasets.errors import DatasetValidationError

COMMERCIAL_LICENSES = frozenset(
    {
        "Apache-2.0",
        "MIT",
        "BSD-2-Clause",
        "BSD-3-Clause",
        "CC0-1.0",
        "CC-BY-4.0",
        "ODC-By-1.0",
        "Proprietary-GuardianAI",
    }
)
"""Licences under which a dataset may train a model Guardian ships.

Deliberately short. Share-alike terms (CC-BY-SA, ODbL) are absent because
whether a share-alike dataset obliges Guardian to publish derived *weights*
is unsettled, and an allowlist is the wrong place to guess."""

RESEARCH_LICENSES = frozenset(
    {
        "CC-BY-NC-4.0",
        "CC-BY-NC-SA-4.0",
        "CC-BY-NC-ND-4.0",
        "Research-Only",
        "Academic-Only",
    }
)
"""Known non-commercial terms. Publishable for evaluation, never for
training a shipped model. OmniFall (CC-BY-NC-SA) is the concrete case that
made this list necessary."""


class DatasetUsage(Enum):
    """What a published dataset version is permitted to be used for."""

    TRAINING = "training"
    """Full use, including training a model that reaches the zoo. Requires a
    licence on ``COMMERCIAL_LICENSES``."""

    EVALUATION_ONLY = "evaluation-only"
    """Loadable and scoreable; refused by the promotion gate as a training
    source. This is how research-licensed corpora stay useful without
    becoming a licence liability."""


def check_dataset_license(license_id: str, usage: DatasetUsage, dataset_name: str) -> None:
    """Refuse a licence/usage pair that Guardian has no right to publish.

    Raises DatasetValidationError, which the publish path turns into a
    refusal that leaves no trace on disk.
    """
    identifier = license_id.strip()
    if not identifier:
        raise DatasetValidationError(
            f"dataset '{dataset_name}': no license declared — an unstated licence "
            f"is not a permissive one (ADR-0005 §5)"
        )
    if identifier in COMMERCIAL_LICENSES:
        return
    if identifier in RESEARCH_LICENSES or _looks_non_commercial(identifier):
        if usage is DatasetUsage.EVALUATION_ONLY:
            return
        raise DatasetValidationError(
            f"dataset '{dataset_name}': license '{identifier}' does not permit "
            f"commercial use, so it cannot be published for training a shipped "
            f"model. Publish it with usage '{DatasetUsage.EVALUATION_ONLY.value}' "
            f"to measure against it instead (ADR-0005 §5)"
        )
    raise DatasetValidationError(
        f"dataset '{dataset_name}': license '{identifier}' maps to no known term. "
        f"Commercial-permissive licences are {sorted(COMMERCIAL_LICENSES)}; "
        f"non-commercial terms are publishable only as "
        f"'{DatasetUsage.EVALUATION_ONLY.value}' (ADR-0005 §5)"
    )


def _looks_non_commercial(identifier: str) -> bool:
    """Catch the spellings an allowlist will always be one behind on.

    A false positive here costs an engineer one explicit ``evaluation-only``
    declaration. A false negative costs a licence violation in a product.
    """
    lowered = identifier.lower()
    return any(
        marker in lowered
        for marker in ("-nc", "noncommercial", "non-commercial", "research", "academic")
    )
