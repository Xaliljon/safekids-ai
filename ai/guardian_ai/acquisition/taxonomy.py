"""Guardian video taxonomy v1 — safety states only, never identities.

Nine labels, two kinds:

- BOX labels describe *who is visible* (person/child/adult/unknown) —
  the same scene-state vocabulary as ADR-0010, never who someone is.
- EVENT labels describe *what is happening over time* (fall, walking,
  standing, sitting, lying, unknown).

No identity labels. No face labels. No names. A taxonomy is the outer
fence of what a Guardian dataset can ever express — identity cannot be
annotated because it cannot be represented (docs/04).
"""

from __future__ import annotations

from guardian_ai.datasets.taxonomy import LabelDefinition, LabelTaxonomy

GUARDIAN_VIDEO_TAXONOMY_V1 = LabelTaxonomy(
    name="guardian-video-safety",
    version="1.0.0",
    labels=(
        LabelDefinition("person", "Any visible human, when age group is not annotated"),
        LabelDefinition("child", "Person annotators judge to be a child"),
        LabelDefinition("adult", "Person annotators judge to be an adult"),
        LabelDefinition("fall", "A person falling — the transition, not the aftermath"),
        LabelDefinition("walking", "Person walking"),
        LabelDefinition("standing", "Person standing"),
        LabelDefinition("sitting", "Person sitting"),
        LabelDefinition("lying", "Person lying down (incl. post-fall)"),
        LabelDefinition("unknown", "State visible but not confidently classifiable"),
    ),
)

BOX_LABELS = frozenset({"person", "child", "adult", "unknown"})
EVENT_LABELS = frozenset({"fall", "walking", "standing", "sitting", "lying", "unknown"})

# Vocabulary that must never appear anywhere near a Guardian dataset —
# not as labels, not as metadata keys (privacy gate uses the same list).
FORBIDDEN_LABEL_TERMS = frozenset(
    {"face", "identity", "name", "recognition", "gender", "ethnicity", "emotion"}
)


def is_box_label(label: str) -> bool:
    return label in BOX_LABELS


def is_event_label(label: str) -> bool:
    return label in EVENT_LABELS
