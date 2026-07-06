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
