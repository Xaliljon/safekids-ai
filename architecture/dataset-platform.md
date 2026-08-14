# Dataset Management Platform

- **Date:** 2026-07-05 (Sprint 7)
- **Reflects:** ADR-0010 (dataset platform), ADR-0005 (governance), docs/04 (dataset ethics)
- **Scope:** dataset infrastructure in `ai/` — no training, no models

## Purpose

The foundation future AI research stands on: every dataset is versioned,
consent-documented, quality-gated, privacy-checked, and measured *before*
anything trains on it. Built before the first byte of real data exists, so
the wrong workflow is never an option.

## Modules (`ai/guardian_ai/datasets/`)

| Module | Responsibility |
|---|---|
| `annotations.py` | JSONL annotation format: `SampleRecord` / `Annotation` / normalized `BoundingBox` (same [0,1] top-left convention as edge detections, ADR-0006) |
| `taxonomy.py` | Versioned label vocabulary; V1 = `person`, `child`, `adult` — scene states, never identities |
| `manifest.py` | `dataset.json`: identity, taxonomy binding, **required** provenance & privacy declarations |
| `splits.py` | Deterministic hash-based train/val/test assignment — reproducible, stable under dataset growth |
| `quality.py` | Structural gate: duplicates, cross-split leakage, unknown labels, empty splits (ERROR blocks; WARNING surfaces) |
| `privacy.py` | Ethics floor: consent reference, minors ⇒ review reference, identity attribute keys, email/phone patterns, escaping paths |
| `metrics.py` | Label balance, split composition, background share, imbalance ratio — inputs to the docs/04 bias review |
| `registry.py` | Versioned, immutable, gated filesystem registry (mirrors the model zoo, ADR-0009) |
| `versioning.py` | Semantic dataset versions |
| `licensing.py` | Commercial allowlist + `DatasetUsage` (training vs evaluation-only), ADR-0005 §5 |
| `lifecycle.py` | `Tombstone` / `DatasetLifecycle` — withdrawal and expiry beside an immutable version, ADR-0005 §§4, 7 |

## Registry layout

```
<root>/
  .staging/                      # in-flight publishes; swept at startup
  kindergarten-scenes/
    1.0.0/
      dataset.json               # finalized: checksums + counts written at publish
      annotations/
        train.jsonl
        val.jsonl
        test.jsonl
```

Media files are **not** here: they live in DVC-managed storage and are
referenced by relative path (raw child video never enters git or the
registry — `datasets/README.md`).

## Publish pipeline

```
bundle (dataset.json + annotations/*.jsonl)
  │ 1. manifest valid (semver, taxonomy binding, provenance, privacy declared)
  │ 2. taxonomy binding matches the taxonomy being published against
  │ 3. every split parses strictly (errors carry file:line)
  │ 4. quality gate: no ERRORs (leakage, duplicates, unknown labels, empty splits)
  │ 5. privacy gate: no violations (consent, minors review, identity data, paths)
  │ 6. licence gate: known term, and non-commercial only as evaluation-only
  │ 7. finalize manifest (sha256 + sample counts) -> staged copy -> atomic rename
  └─ get() re-verifies checksums — post-publication edits are detected
```

A refused publish leaves no trace. Versions are immutable; ship a new one.

## Governance (ADR-0005)

Three refusals were added once the ADR had to be built rather than written.

**Withdrawal outranks immutability.** ADR-0010 froze published versions so
a run reproduces exactly; a guardian withdrawing consent needs the material
gone. Consent wins, and the mechanism keeps both properties: withdrawal
never edits the version — that would break the checksums that make it
auditable — it writes `tombstone.json` beside the manifest.

| Call | Behaviour on a tombstoned version |
|---|---|
| `get(name, version)` | refuses, quoting the reason, who recorded it, and when |
| `get(name)` (latest) | **skips** it — withdrawal publishes a replacement, and that is what "latest" must mean |
| `get_for_audit(name, version)` | returns it, tombstone attached — a director asking what happened is answered from here |
| `withdraw()` / `expire()` | write the tombstone; never overwrite one, because a withdrawal record is evidence |

Media deletion happens in DVC storage. The manifest stays: destroying the
record of what a deployed model learned from serves nobody, least of all
the parent who asked.

**Licence and use are separate questions.** Guardian's own importers record
Le2i as "research use" and UR Fall as "free for research use". A flat
non-commercial refusal would have blocked the corpora queued to fix the
scene leakage while leaving the real risk unstated, so a version declares
`usage`:

- `training` — needs a licence on the commercial allowlist; may reach the zoo.
- `evaluation-only` — loadable and scoreable; refused by the promotion gate.

Training a shipped detector on research footage is the use those terms
withhold; measuring against a held-out research corpus is an instrument.
So the refusal sits at promotion, where a licence question becomes a
shipping question.

**Minors need a resolvable review.** A registry constructed without a
`review_resolver` cannot publish material depicting minors at all, and one
with a resolver refuses a reference that resolves to nothing. Such a
dataset must also state `privacy.retention_until` — material with no end
date is material nobody ever deletes.

`promote()` requires the dataset registry rather than accepting `None`: a
gate that skips when its dependency is absent would report success on the
day it mattered. The CLI reads that registry out of the run's own config,
so an approver cannot aim the check at a registry where the withdrawal
never landed. Runs trained outside the registry (the COCO baseline) are not
refused but are stamped `dataset_verified: false` in the promotion record.

## The dataset.json contract

```json
{
  "name": "kindergarten-scenes",
  "version": "1.0.0",
  "description": "...",
  "taxonomy": {"name": "guardian-safety", "version": "1.0.0"},
  "created_utc": "2026-07-05T12:00:00Z",
  "provenance": {
    "collected_by": "Guardian AI pilot team",
    "consent_reference": "consent/agreement-2026-001"
  },
  "privacy": {
    "contains_minors": true,
    "anonymized": true,
    "review_reference": "ethics/review-2026-007"
  },
  "splits": {
    "train": {"file": "train.jsonl", "sha256": "…", "samples": 4210},
    "val":   {"file": "val.jsonl",   "sha256": "…", "samples": 530}
  },
  "license": "Proprietary-GuardianAI"
}
```

Consent and the minors/review pairing are enforced by the privacy gate —
a dataset of children without a documented ethics review cannot publish.

## Deterministic splits

`assign_split(path)` hashes the sample path into [0, 1) and walks the
cumulative ratios (default 80/10/10). Properties: reproducible everywhere,
no seed to lose, and **growth-stable** — new samples never move existing
ones between splits, so evaluation sets stay honest across dataset
versions. Grouped splitting (per camera session) is a planned extension of
the split key.

## What this deliberately does not do

Train models, read pixels, or claim ethics compliance: the privacy checker
is a mechanical floor, and the manifest points at human review documents
(`review_reference`) rather than asserting approval itself.
