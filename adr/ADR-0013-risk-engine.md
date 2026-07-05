# ADR-0013: Risk Engine (Safety Incidents)

- **Status:** Accepted
- **Date:** 2026-07-05
- **Deciders:** Founder, Lead Software Architect

## Context

Candidate events (ADR-0012) are suspicions; directors need *incidents* —
deduplicated, severity-rated, reviewable units of "something may have
happened to this child". Between them sits policy: when do suspicions
become actionable, how do repeats aggregate, how are false positives kept
from eroding trust (docs/13: directors do not want alert spam), and how is
the human-decides rule made structural rather than procedural.

## Decision

1. **The incident is the unit of human review, and auto-resolution is
   unrepresentable.** `SafetyIncident` is born `PENDING_REVIEW`; the only
   exits are `confirmed()`/`dismissed()`, both requiring an identified
   reviewer — the domain refuses blank reviewers, double resolutions, and
   post-resolution evidence. No code path in the engine closes its own
   incidents (docs/04 §5, human oversight is mandatory).

2. **The risk engine is an EventConsumer.** The fifth layer in a row to
   compose through a callable seam — detections → tracks → candidates →
   incidents — each layer untouched by the next. The notification engine
   attaches downstream as `IncidentConsumer`, receiving every snapshot
   (opened, corroborated, escalated, resolved) under one `incident_id`.

3. **Rules are declarative policies per event type** (`RiskPolicySet`):
   confidence gate, fast-path threshold, corroboration requirement,
   aggregation window, dismissal-suppression window, severity cutoffs.
   Every number is a reviewable product decision; deployments tune data,
   not code. Defaults align the risk gate with the event engine's emission
   threshold — layers agree by default and diverge only deliberately
   (mismatched defaults silently swallowed the weakest-but-first candidate
   during development; that lesson is encoded here).

4. **Correlation: one open incident per (camera, track, type).** While an
   incident is pending, every further qualifying candidate on that track
   *attaches* to it — an unresolved situation is one situation, however
   long the human takes. The aggregation window governs only pre-open
   corroboration buffering. `correlation_id` anchors to the first
   triggering capture (ADR-0007).

5. **Risk confidence is noisy-or across attached evidence**
   (`1 − Π(1 − cᵢ)`): independent corroborating suspicions compound —
   two 0.7 candidates yield 0.91, not max(0.7). Severity derives from
   policy cutoffs (LOW/MEDIUM/HIGH/CRITICAL) and may only escalate as
   evidence attaches; escalations are counted and emitted.

6. **False-positive suppression is layered:** the per-candidate confidence
   gate; optional N-of-M corroboration before opening (with a fast path
   for single high-confidence events); the single-open-incident rule (no
   duplicate alerts for one situation); and a post-dismissal suppression
   window — a false positive a director just dismissed must not ring
   again seconds later.

## Consequences

- Directors will see one MEDIUM incident per fall candidate by default —
  deliberately conservative for a safety product (the failure mode is one
  glance at a pending item, not a missed child); corroboration tightens
  per deployment via policy, not code.
- Dismissals are recorded per incident with reviewer identity — the
  beginnings of the false-positive dataset the learned detectors
  (ADR-0012 §3) will train against.
- Open incidents live in engine memory pending review; persistence and
  the `contracts/events` incident schema arrive with the notification/
  backend sprint, where incidents first cross the device boundary.
- Suppression windows are keyed by track id; a re-identified person (new
  track after long occlusion) is not suppressed. Acceptable: over-alerting
  on identity breaks errs toward safety.

## Alternatives Considered

- **Auto-expiry of unreviewed incidents:** rejected — silently expiring a
  possible injury is the one unacceptable failure mode; unreviewed
  incidents stay open and visible.
- **Severity = max event confidence:** rejected — ignores corroboration;
  three medium-confidence falls on one child are not a medium situation.
- **Learned risk scoring:** premature — no outcome data exists; the
  policy structure and review records are how that data gets collected.
- **Notifications inside the risk engine:** rejected — delivery,
  recipients, and channels are a separate concern (docs/03, single
  responsibility); the IncidentConsumer seam is the handoff.
