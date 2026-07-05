# Risk Engine

- **Date:** 2026-07-05 (Sprint 11)
- **Reflects:** ADR-0013 (risk engine), ADR-0012 (event engine), ADR-0007 (identity)
- **Scope:** candidate → incident conversion; no notifications, no persistence yet

## Purpose

Converts candidate events into **SafetyIncidents** — deduplicated,
severity-rated, evidence-carrying units a director reviews. The full V1
detection chain now exists end-to-end on the edge:

```
camera → detections → tracks → candidates ──EventConsumer──> RiskEngine ──IncidentConsumer──> (notifications, later)
                                                   │
                                        confirm()/dismiss() ← human reviewer
```

## The incident (`domain/incident.py`)

`SafetyIncident`: id, type, camera/track binding, severity, aggregated
risk confidence, the full tuple of corroborating `CandidateEvent`s
(evidence chain intact to frames, ADR-0007), human-readable summary, and
**status**. Invariants the domain enforces:

- born `PENDING_REVIEW`; review present *iff* resolved
- resolution requires an identified reviewer; double resolution impossible
- resolved incidents accept no new evidence; evidence must match the
  incident's camera, track, and type; an incident without evidence cannot exist

## The rule engine (`application/risk/policy.py`)

`RiskPolicySet` — one declarative `RiskPolicy` per event type:

| Rule | Default (POTENTIAL_FALL) | Meaning |
|---|---|---|
| `min_event_confidence` | 0.6 (= event engine threshold) | suppress weaker candidates outright |
| `fast_path_confidence` | 0.85 | single strong candidate opens immediately |
| `min_events_to_open` | 1 | corroboration requirement otherwise (falls: one qualifying candidate opens — conservative toward safety) |
| `aggregation_window_seconds` | 30 | pre-open corroboration window |
| `dismissal_suppression_seconds` | 60 | dismissed track stays quiet |
| `medium_at / high_at / critical_at` | 0.6 / 0.75 / 0.85 | severity cutoffs over risk confidence |

## Engine behavior (`application/risk/engine.py`)

- **Correlation:** one open incident per (camera, track, type); further
  qualifying candidates attach while it is pending — an unresolved
  situation is one situation. Consumers see updated snapshots under the
  same `incident_id`.
- **Risk confidence:** noisy-or over attached evidence
  (two 0.7 candidates → 0.91); severity only escalates, and escalations
  are counted and emitted.
- **False-positive suppression (layered):** confidence gate → optional
  corroboration-before-open → single-open-incident → post-dismissal
  suppression window.
- **Human review:** `confirm(id, reviewer)` / `dismiss(id, reviewer)` are
  the only exits; dismissals start the suppression window and are counted
  (the seed of the future false-positive training set).
- **Robustness:** consumer failures isolated and counted; stats expose
  received/suppressed/opened/correlated/escalated/confirmed/dismissed and
  per-severity opens.

## Verified (25 new tests)

Opening on a qualifying candidate (MEDIUM, pending); low-confidence and
post-dismissal suppression with expiry; corroboration requirement, fast
path, and window expiry; attach + escalate (0.7+0.7 → CRITICAL) under one
incident id; per-track separation; correlation anchor; confirm/dismiss
with reviewer identity enforced; resolved incidents leaving the open set;
consumer failure isolation; and the deliverable chain —
**fall trajectory → EventEngine → RiskEngine → PENDING_REVIEW
SafetyIncident → confirmed by a named reviewer**.

## Out of scope (later)

Notification engine (attaches as `IncidentConsumer`), incident persistence
and the `contracts/events` schema (arrive when incidents first cross the
device boundary), evidence clip storage, zone-exit/cry policies, learned
risk scoring (trained on accumulated review decisions).
