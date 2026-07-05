# ADR-0012: Event Engine (Candidate Safety Events)

- **Status:** Accepted
- **Date:** 2026-07-05
- **Deciders:** Founder, Lead Software Architect

## Context

SafeKids V1 must turn track streams into *potential safety events* (charter:
fall detection first). The layer between tracking and humans splits in two:
an **event engine** that computes explainable candidates from geometry, and
a future **risk engine** that decides severity, aggregation, and what
reaches a director. Sprint 10 builds the first; conflating them would put
alerting policy inside signal math and violate the human-in-control
layering (docs/04).

## Decision

1. **Candidates, not conclusions.** The engine emits `CandidateEvent`s —
   "this looks like a potential fall, confidence 0.8, because of these
   signals". Candidates trigger nothing by themselves. The domain type
   *refuses construction without signals*: an unexplainable event cannot
   exist (docs/04, explainability).

2. **The engine is a TrackConsumer.** `EventEngine(result)` attaches to
   the vision pipeline's existing seam exactly as the tracker attached to
   detections — zero pipeline changes, camera service and inference
   runtime untouched. The risk engine will attach to the engine's
   `EventConsumer` the same way. Failures are isolated per detector and
   per consumer, counted, never fatal.

3. **Geometry heuristics first, models later, same port.** Fall candidates
   come from four explainable signals over per-track history: peak
   downward velocity (hard gate — no downward motion, no candidate),
   aspect-ratio flip (tall→wide vs the track's own baseline), ground
   proximity (lower-edge position), and post-event stillness. Confidence
   is their weighted mean. No pose estimation, no learned classifier —
   when the dataset platform (ADR-0010) has real fall data, a trained
   detector replaces this behind the same `CandidateDetector` port and
   must beat it on the recorded metrics.

4. **Evidence rules.** History stores CONFIRMED observations only — LOST
   tracks carry Kalman *predictions*, and predictions never masquerade as
   evidence. Velocity is measured across ≥150 ms spans so detection jitter
   cannot read as a fall. Per-track cooldown makes a candidate a discrete
   piece of evidence, not a per-frame spam stream.

5. **ADR-0007 end-to-end.** Every candidate carries the triggering frame's
   `frame_id`/`correlation_id`, plus the full track snapshot whose
   `last_detection` holds detection-level identity — notification →
   candidate → track → detection → frame stays traceable.

## Consequences

- Measured: p50 0.13 ms / p95 0.14 ms per frame at 12 tracks — the whole
  event layer is noise within the < 1 s alert budget.
- Heuristics have known blind spots (falls toward the camera change aspect
  ratio little; couches are "low in frame"). Acceptable for a *candidate*
  generator whose output humans review; the risk engine and later learned
  models raise precision. Thresholds are physical statements in one config
  object, tunable per deployment.
- Ground proximity is an uncalibrated proxy (image-space). Scene
  calibration (floor-zone annotation per camera) is a planned config
  input, not an architecture change.
- The `contracts/events` schema should mirror `CandidateEvent` when the
  backend starts receiving events (flagged for the risk-engine sprint).

## Alternatives Considered

- **Pose-estimation-based fall detection now:** rejected for this sprint —
  a second model on every frame, keypoint models have their own licensing
  and latency questions, and the sprint explicitly scopes it out. The
  signal set is designed so pose-derived signals can join the same
  weighted combination later.
- **Learned classifier over track features:** blocked on data that does
  not exist yet; the dataset platform exists precisely to collect it. The
  heuristic's signals double as the future feature set.
- **Emitting alerts/notifications directly:** rejected — severity and
  delivery policy belong to the risk engine; this layer must stay a pure
  evidence producer (docs/04).
- **Event engine inside the tracker:** rejected — tracking is identity,
  events are interpretation; separate ports keep both replaceable.
