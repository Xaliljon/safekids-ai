# ADR-0007: Detection Identity and Correlation

- **Status:** Accepted
- **Date:** 2026-07-05
- **Deciders:** Founder, Lead Software Architect

## Context

Tracking, the risk engine, analytics, and notifications will all consume
detections — across threads, queues, storage, and eventually devices. They
need to join records back to frames and cameras, trace an alert back to the
exact capture that caused it (docs/04, explainability), and deduplicate or
aggregate safely. That requires a deliberate identity model *before* those
subsystems exist; retrofitting identifiers later would touch every consumer.

## Decision

1. **Every detection is self-contained.** `Detection` carries five
   identifiers: its own `detection_id` (UUID), `frame_id` (UUID),
   `camera_id`, `captured_at` (UTC), and `correlation_id` (UUID). A
   detection can be queued, stored, or shipped alone and still be fully
   attributable — no joins against in-memory objects required.

2. **Identity is minted at the source, once.**
   - `frame_id` and `correlation_id` are minted at capture, in the `Frame`
     constructor (`default_factory=uuid4`) — impossible to forget, and the
     camera service stays AI-ignorant (nothing changed in capture code).
   - `detection_id` is minted by the detector that creates the detection.
   - Downstream stages **propagate ids and never regenerate them.**

3. **`frame_id` and `correlation_id` are distinct on purpose.** `frame_id`
   identifies the captured *image* (`sequence` remains a human-readable
   per-stream counter that resets on reconnect and is not an identity).
   `correlation_id` is the *trace token* of the causal chain started by that
   capture: detections, tracks, risk events, notifications, and analytics
   records all carry it, so one alert can be traced end-to-end. They are 1:1
   at capture today; they diverge when a frame is ever re-processed
   (replay, re-analysis, A/B detectors) — same `frame_id`, new chain.

4. **Consistency is enforced in the domain.** `DetectionResult` rejects
   detections whose `frame_id`, `camera_id`, or `correlation_id` disagree
   with its own — a mixed-up result cannot be constructed.

5. **UUIDs, not sequential integers.** Identifiers must be unique across
   cameras, restarts, and eventually a fleet of edge boxes whose records
   merge in one backend; coordination-free UUIDs make that safe.
   `DummyDetector` derives deterministic UUIDv5 ids from the frame id so
   its full determinism guarantee (same frame → identical result, ids
   included) still holds; real detectors use random UUIDv4.

## Consequences

- Downstream subsystems get stable join keys (`frame_id`, `correlation_id`)
  and a per-record primary key (`detection_id`) from day one; the future
  contracts/events schema will mirror these fields.
- Detections carry ~5 extra fields of denormalized metadata; at edge
  detection volumes this is negligible, and it buys queue/storage
  independence.
- Detector implementations are responsible for propagating frame identity;
  the `DetectionResult` invariant turns mistakes into immediate,
  deterministic construction errors rather than silent data corruption.

## Alternatives Considered

- **Pipeline stamps ids after detection:** rejected — splits the identity
  of one record across two writers and lets an unstamped `Detection` exist
  in the meantime; the domain type should be impossible to construct
  half-identified.
- **`correlation_id == frame_id` (one field):** rejected — conflates data
  identity with chain identity and breaks the moment a frame is
  re-processed; the cost of a second UUID is trivial next to re-keying
  every downstream system later.
- **Sequential integer ids:** rejected — require coordination to stay
  unique across streams, restarts, and devices; collisions in merged
  analytics would be silent.
- **Identity minted in the vision pipeline (keep capture id-free):**
  rejected — tracking and evidence clips will reference frames that had no
  detections at all; frame identity belongs to capture, not to AI.
