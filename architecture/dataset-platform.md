# Dataset Management Platform

- **Date:** 2026-07-05 (Sprint 7)
- **Reflects:** ADR-0010 (dataset platform), docs/04 (dataset ethics)
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
  │ 6. finalize manifest (sha256 + sample counts) -> staged copy -> atomic rename
  └─ get() re-verifies checksums — post-publication edits are detected
```

A refused publish leaves no trace. Versions are immutable; ship a new one.

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
