# Evidence Management Platform

- **Date:** 2026-07-06 (Sprint 16)
- **Reflects:** ADR-0017 (evidence management), ADR-0007 (identity), ADR-0016 (ops)
- **Scope:** incident video evidence, encrypted storage, retention, serving; no engine changes

## Purpose

Visual proof for every safety incident — without becoming a recording
system. The circular buffer forgets everything on its own; only a
SafetyIncident turns 30 seconds of it into an encrypted file.

```
             (fan-out in the supervisor — every seam already existed)
 cameras ──FrameConsumer──┬─> VisionPipeline ── TrackConsumer ─┬─> EventEngine → RiskEngine
                          │                                    │                    │ IncidentConsumer
                          v                                    v                    ├──> NotificationEngine (alert first)
                 FrameRingBuffer (RAM,                TrackRingBuffer (RAM,         └──> EvidenceRecorder (async)
                 ~30s JPEG per camera,                per-frame track tuples)                │ post-roll wait
                 drop-on-backpressure)                         │                             │ slice [-15s,+15s]
                          └────────────────┬───────────────────┘                             v
                                           v                                     original.mp4 + overlay.mp4 + thumb
                                   overlay renderer (export-time:                            │ AES-256-GCM
                                   boxes, ids, confidence, timeline,                         v
                                   incident marker)                        $GUARDIAN_HOME/evidence/<incident-id>/
                                                                                             │ audited, token-gated
                                                                                             v
                                                                    Device API /evidence* ──> SafeKids app (review only)
```

## Components

| Piece | Where | Role |
|---|---|---|
| `FrameRingBuffer` / `TrackRingBuffer` | `infrastructure/evidence/rings.py` | RAM circular buffers; constant-time hot path, JPEG encoding on own thread |
| overlay renderer | `infrastructure/evidence/overlay.py` | AI-analysis variant, drawn at export time |
| `EvidenceVault` + `secure_delete` | `infrastructure/evidence/crypto.py` | AES-256-GCM at rest; key under `data/keys/` (0600), apart from media |
| `FileSystemEvidenceStore` | `infrastructure/evidence/store.py` | per-incident folders, plaintext metadata, append-only `audit.jsonl`, tombstoned deletes |
| `EvidenceRecorder` | `application/evidence/recorder.py` | IncidentConsumer → async export of both variants + thumbnail |
| `EvidenceRetentionService` | `application/evidence/retention.py` | dismissed 24 h / confirmed+pending 30 d / critical 90 d |
| Device API routes | `api/server.py` | `/evidence`, `/{id}`, `/{id}/video?variant=`, `/{id}/thumbnail` — trusted devices only |
| Evidence domain | `domain/evidence.py` | Evidence, statuses, clip variants, retention policy, future types |

## Identity (ADR-0007)

Every evidence record stores `incident_id`, `track_id`, `detection_id`,
`frame_id`, `correlation_id` — the exact detection and frame that
evidenced the incident. A clip is traceable back through risk → tracking
→ detection → capture, and forward to every notification.

## Performance guarantees

- `on_frame` = bounded `put_nowait` (drops oldest on overflow) — measured
  worst case under concurrent export load: **< 10 ms for 1000 frames
  total** (stress test); typical sub-100 µs.
- JPEG encode, overlay drawing, mp4 encode, encryption: all on background
  threads; the recorder queue decouples the Risk Engine completely.
- Memory: ≈ 30 MB per camera at defaults (30 s, 10 fps, ~100 KB/frame).

## Storage bounds (ADR-0019)

Retention is age-based and every clip does expire — but age never bounded
the disk. A box opening incidents faster than its shortest window (24 h for
dismissed) accumulates without limit: **2602 records and 152 GB** were
measured in a few hours against a looping test clip, with the sweeper
running correctly the entire time and nothing yet old enough to expire.

The sweeper now runs a budget pass after the age pass, evicting until the
evidence directory is inside `max_total_bytes` (20 GB default) and the
filesystem is above `min_free_bytes` (10 GB — twice the installer's own
refusal threshold, so the budget bites before the box endangers anything
else). Sizes come from each record's clip metadata, so a sweep costs no
directory walk.

**Eviction order is by review state, not age.** Dismissed first, then
confirmed, then pending review; CRITICAL last within each class; oldest
first within that. Strict oldest-first is simpler and wrong — on a busy box
the oldest records are the ones waiting longest for a human, which is
exactly the evidence most likely to matter.

Evicting evidence nobody has reviewed is logged at warning level, counted,
and reported through `/health` as a **degraded** evidence subsystem. That
state says the box is opening incidents faster than they can be reviewed;
the fix is upstream in the risk policy, not a bigger disk.

The metadata tombstone always survives: a director loses the footage, never
the fact that an incident existed and what was decided about it.

## Failure & recovery

| Failure | Behavior |
|---|---|
| empty/short buffer at incident time | record marked FAILED with reason; app explains honestly |
| recorder crash | watchdog restarts the thread; FAILED record persists |
| shutdown during post-roll | exports whatever the ring holds (partial clip beats no clip) |
| tampered/foreign media file | AES-GCM integrity check refuses to serve |
| corrupt metadata folder | skipped and logged; other evidence unaffected |

## Testing (53 evidence tests, 94% line coverage on the subsystem)

Rings (window, eviction, isolation, non-blocking-when-jammed), overlay
(boxes/marker drawn, input never mutated), crypto (roundtrip, key modes,
wrong-key/tamper/foreign refusal, secure delete), store (layout, audit,
tombstones), recorder (READY end-to-end with decodable mp4s, identity
chain, dedup, FAILED paths, mid-shutdown export), retention (each policy
lifetime, decision-driven shortening, tombstone idempotence), Device API
(401s for unpaired/forged tokens, variants, audit entries, disabled mode)
and a stress run (exports under sustained frame load).
