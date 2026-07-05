# Event Engine

- **Date:** 2026-07-05 (Sprint 10)
- **Reflects:** ADR-0012 (event engine), ADR-0011 (tracking), ADR-0007 (identity)
- **Scope:** candidate generation only — no risk engine, no notifications, no pose

## Purpose

Turns per-track motion history into **explainable candidate safety
events** — the AI's suspicions, never its conclusions. The first candidate
type is `POTENTIAL_FALL` (charter, SafeKids V1 event #1). The future risk
engine consumes candidates and decides what reaches humans; humans decide
what is true (docs/04).

## Position in the chain

```
camera -> vision pipeline -> ByteTrack ──TrackConsumer──> EventEngine ──EventConsumer──> (risk engine, later)
                                          per-track history    candidate detectors
```

The engine is a plain `TrackConsumer` — the pipeline is untouched, exactly
how each layer has attached to the previous one since ADR-0006.

## Components (`application/events/`)

| Module | Responsibility |
|---|---|
| `history.py` | `TrackHistoryStore`: bounded time-window of observations per track (motion + shape history). **CONFIRMED observations only** — LOST tracks are Kalman predictions, and predictions are not evidence. |
| `features.py` | Pure measurements over history: peak downward velocity (≥150 ms spans — jitter can't read as a fall), average speed, aspect-ratio baseline vs current, ground proximity (lower-edge position), stillness score. |
| `fall.py` | `PotentialFallDetector`: gate on downward velocity, then weighted combination of four signals → confidence; per-track cooldown. All thresholds are physical statements in `FallDetectorConfig`. |
| `engine.py` | `EventEngine`: history upkeep, detector fan-out per confirmed track, guarded emission, stats (frames, evaluations, emissions per type, errors, p50/p95 latency). |
| `ports.py` | `CandidateDetector` (evaluators return a candidate or None; they never publish) and `EventConsumer` (where the risk engine attaches). |

## The fall heuristic

A fall, to a fixed camera, is a *combination*:

| Signal | Measurement | Weight |
|---|---|---|
| `downward_velocity` | peak center-y speed, gated (no downward motion ⇒ never a candidate) | 0.35 |
| `aspect_ratio_flip` | width/height now vs the track's own early baseline (tall → wide) | 0.25 |
| `ground_proximity` | lower-edge position in frame (uncalibrated proxy; per-camera floor zones later) | 0.20 |
| `stillness` | movement over the trailing second (post-fall stillness) | 0.20 |

Confidence = weighted mean; candidates emit at ≥ 0.6 with a 10 s per-track
cooldown. Every emitted event carries all four signals with human-readable
measurements — `CandidateEvent` **cannot be constructed without signals**.

Verified behaviors (35 new tests): a synthetic fall produces exactly one
candidate ≥ 0.6; walking and slow sitting produce none; a fall followed by
crawling scores lower than a fall followed by stillness; unmonitored labels
are never evaluated; broken detectors/consumers are isolated and counted;
the full chain (scripted detections → ByteTrack → engine) emits one
candidate end-to-end.

## Identity (ADR-0007)

`CandidateEvent` carries the triggering frame's `frame_id` and
`correlation_id` plus the full `Track` snapshot (whose `last_detection`
holds detection-level identity): notification → candidate → track →
detection → captured frame remains one traceable chain.

## Measured

p50 **0.13 ms** / p95 **0.14 ms** per frame at 12 concurrent tracks
(`make bench`) — the event layer is noise inside the < 1 s alert budget.

## Out of scope (later)

Risk engine (severity, aggregation, delivery policy), notifications,
pose-derived signals, learned classifiers (trained on ADR-0010 datasets,
plugged behind the same `CandidateDetector` port), zone-exit and cry
candidates, per-camera floor calibration, `contracts/events` schema for
backend transport.
