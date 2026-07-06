# Guardian Dataset Platform v1 — Acquisition & Annotation

- **Date:** 2026-07-06 (Sprint 18)
- **Reflects:** ADR-0007 (identity chain), ADR-0009/0010 (registries), ADR-0017 (evidence)
- **Scope:** datasets only — no training, no AI, no Edge changes

## Dataset lifecycle

```
 Open datasets                     Guardian pilot
 (UR Fall, Le2i, GMDCSA24)         (Edge evidence export)
        │                                │
        ▼                                ▼
   importer (documented raw layout; raw data NEVER used directly)
        │
        ▼
   normalize video ──► H.264/yuv420p · 640x480 letterboxed · 15 fps ·
        │              metadata stripped · byte-DETERMINISTIC encode
        ▼
   convert annotations ──► Guardian Video Annotation v1 (validated, or rejected)
        │
        ▼
   guardian_dataset_v1 workspace          review workflow
   ┌────────────────────────────┐         IMPORTED
   │ dataset.json   (ethics)    │            ↓ (annotation tool)
   │ train/ val/ test/          │         ANNOTATED
   │ videos/  annotations/      │            ↓ (human reviewer)
   │ metadata/  taxonomy/       │         REVIEWED
   └────────────────────────────┘            ↓ (named approver)
        │                                 APPROVED
        ▼                                    ↓
   publish gates: quality ─► privacy ─► statistics ─► training export
        │
        ▼
   Guardian Dataset Registry  <root>/<name>/<version>/   (immutable,
   checksummed, PUBLISHED state recorded)
        │
        ▼
   training/ (data.yaml + images/ + labels/) — Sprint 19 consumes this
```

Everything lives in `ai/guardian_ai/acquisition/` + the
`python -m guardian_ai.dataset` CLI. Nothing imports edge code.

## Unified format: guardian_dataset_v1

| Path | Contents |
|---|---|
| `dataset.json` | ethics-bearing manifest: provenance (`collected_by`, `consent_reference`), privacy posture (`contains_minors`, `anonymized`, `review_reference`), taxonomy binding, license |
| `train/ val/ test/` | split membership (`clips.jsonl`); assignment is the ADR-0010 hash of the clip id — seedless, stable under growth |
| `videos/` | normalized clips only |
| `annotations/` | one Guardian Video Annotation v1 JSON per clip |
| `metadata/` | per-clip provenance + `review.json` + `quality-report.json` + `dataset-report.pdf` |
| `taxonomy/` | the bound taxonomy snapshot |

## Taxonomy v1 (guardian-video-safety@1.0.0)

Nine labels, two kinds — **box** labels say who is visible
(`person`, `child`, `adult`, `unknown`); **event** labels say what happens
over time (`fall`, `walking`, `standing`, `sitting`, `lying`, `unknown`).
No identity labels, no face labels, no names: identity cannot be annotated
because the format cannot represent it (docs/04).

## Annotation format & tool

`guardian-video-annotation/1`: per-frame normalized boxes ([0,1],
top-left origin — the ADR-0006/0010 geometry) + event spans in frames of
the *normalized* timeline. Validation rejects malformed input outright:
out-of-range boxes, non-positive sizes, event spans outside the clip,
start>end, confidences outside [0,1], wrong-kind labels, duplicate frames.

The annotation tool is a **local web page over a headless session**
(`annotate --workspace … --clip …`): stdlib HTTP server on 127.0.0.1, no
cloud, no CDN. Play/frame-stepping, drag-to-draw boxes, event timeline,
keyboard shortcuts, undo/redo (bounded history), autosave on every edit;
"export Guardian format" is simply save — the tool has no other format.
All logic lives in `AnnotationSession`, tested without a browser.

## Review workflow

`IMPORTED → ANNOTATED → REVIEWED → APPROVED → PUBLISHED`, strictly
forward, one step at a time, every transition recorded with **who, when
and notes** in `metadata/review.json`. Publication requires APPROVED and
re-reads the approval entry into the published `version.json` — reviewer
name, approval time and review notes ship with the dataset.

## Quality & privacy gates

**Quality** (`validate`, and again at publish): missing annotations,
missing/empty/unreadable videos, duplicate videos (content hash),
frozen-still clips (sampled frame hashes), timestamps beyond the actual
video, taxonomy mismatches, malformed annotations. ERRORs block;
WARNINGs surface. Output: `quality-report.json`.

**Privacy** (same cadence): consent reference required; minors require an
ethics review reference; identity-bearing keys (`*_name`, ids, email,
phone, gps, address, face…) forbidden in all metadata; email/phone/GPS
patterns scanned in every string value; face/identity labels rejected.
The checker cannot see pixels — anonymization and consent stay human
responsibilities (ADR-0010), which the manifest must reference.

## Pilot integration & lineage

`import-pilot` consumes a **decrypted evidence export** made on the box
(`<incident-id>/metadata.json` in the ADR-0017 shape + `clip.mp4`,
original view only). ai/ never touches encryption keys. Every imported
clip preserves the full identity chain — `incident_id`, `track_id`,
`detection_id`, `frame_id`, `correlation_id` — giving complete lineage:

    Incident → Evidence → Dataset (clip metadata) → Model (experiment.json
    records dataset name+version — Sprint 17)

Pilot clips are *candidates*: no events (a human annotates; AI never
labels itself), review starts at IMPORTED, nothing publishes
automatically.

## Registry & versioning

`VideoDatasetRegistry` mirrors the model zoo discipline (ADR-0009):
immutable `<name>/<MAJOR.MINOR.PATCH>/` versions, staged atomic installs,
`.staging` swept on startup, SHA-256 of every file recorded at publish
and re-verified on `get()` — a modified published dataset is detected,
not trusted. Existing versions can never be replaced.

## Training-ready export (Sprint 19 prep)

Publish automatically writes `training/` into the version: `data.yaml`
(stable class indices over box labels), `images/{train,val,test}` (only
frames that carry boxes, extracted deterministically), `labels/…`
(`class cx cy w h`, normalized) and a provenance `metadata.json`. No
manual preparation, ever.

## Failure recovery

| Failure | Behavior |
|---|---|
| broken raw layout / malformed source annotations | importer rejects with the exact file/line; nothing partial enters the workspace state |
| unreadable/empty video | normalization or quality gate rejects |
| interrupted publish | staged directory; sweep on next registry start; no partial versions |
| tampered published version | checksum verification on `get()` fails loudly |
| illegal review shortcut | workflow refuses (forward-only, single steps, named actors) |

## Testing

121 platform tests (`ai/tests/test_acq_*`, `test_dataset_cli.py`) over
fabricated raw layouts and synthetic clips: importers (happy + every
documented rejection), normalization determinism (byte-identical
re-encode), annotation validation, session undo/redo/autosave, the HTTP
annotator API, quality and privacy gates, review workflow, registry
immutability + tamper detection, training export, and the CLI end to
end. Coverage over the new modules: 94 %.
