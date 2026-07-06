# Explainable Risk Debugging

- **Date:** 2026-07-06 (Sprint 10.1)
- **Reflects:** ADR-0012 (event engine), ADR-0013 (risk engine), ADR-0007 (identity)
- **Scope:** visibility only — no detection logic, threshold or AI behavior changed

## Purpose

A developer must always know **why** an incident happened — or why it did
not. Every decision the Event Engine and Risk Engine make leaves a trail;
silent failures are forbidden.

```
 pipeline (unchanged decisions)                observation (Sprint 10.1)
 ─────────────────────────────                ───────────────────────────
 VisionPipeline ── detections ──────────────▶ detection counter
      │ tracks
 EventEngine ── unconfirmed tracks ─────────▶ TrackEvaluation("track not confirmed"/"track lost")
      │ confirmed tracks
 PotentialFallDetector ── every evaluate() ─▶ TrackEvaluation(motion + signals + exact reason)
      │ candidates
 RiskEngine ── every candidate ─────────────▶ RiskDecision(outcome + exact reason)
      │ incidents                                        │
 NotificationEngine ── payloads ────────────▶ RiskDebugRecorder
                                                  ├─ logs/risk-debug.log      (one line per decision)
                                                  ├─ reports/<incident-id>/timeline.json  (replay)
                                                  └─ counters ─▶ guardianctl debug (funnel)
```

The hooks are OPTIONAL observers: without one attached the engines run
byte-for-byte as before. Observers are called outside engine locks and a
crashing observer is logged and ignored — explanation can never break or
slow detection.

## Signal calculation (what the numbers mean)

Confidence is a weighted blend of four geometry signals (ADR-0012), each
0..1, computed per confirmed track per frame once the gates pass:

| Signal | Meaning | Saturates at |
|---|---|---|
| velocity | peak downward speed of the body center in the last 1.5 s | 0.6 frame-heights/s |
| aspect ratio | bounding box flipping tall → wide vs its baseline | +1.0 w/h |
| ground contact | lower edge position below the 0.55 line | bottom of frame |
| stillness | lack of movement over the last 1.0 s | fully still |

`confidence = (0.35·velocity + 0.25·aspect + 0.20·ground + 0.20·stillness)`.
The debug line prints exactly these:

```
signals velocity=0.84 aspect_ratio=0.77 ground_contact=0.93 stillness=0.21 final_confidence=0.69
```

Motion analysis (vertical/horizontal velocity, peak downward, movement
delta) is computed for the explanation from the same history — it never
feeds the decision.

## Decision flow and every possible reason

Order matters: the FIRST failing gate is the reason you see.

**Event side (per track, per frame)**
1. `track not confirmed (state: tentative, N hit(s) so far)` / `track lost (N frames without a detection)` — emitted by the Event Engine; detectors never saw this track.
2. `label 'X' is not monitored`
3. `track history too short (0.42s < 1.00s required)`
4. `detector cooldown active (7.3s remaining after the previous candidate on this track)`
5. `downward velocity too low (0.05 < 0.20 frame-heights/s gate)` — hard gate, includes motion numbers.
6. `confidence below threshold (0.42 < 0.60)` — includes the full signal breakdown.
7. `CANDIDATE: all signals combined to 0.69 >= 0.60 threshold`

**Risk side (per candidate)**
1. `no risk policy registered for event type 'X'`
2. `suppressed after human dismissal (52.4s of suppression remaining)`
3. `candidate confidence below policy minimum (0.55 < 0.60)`
4. `awaiting corroboration (1/2 candidate(s) within the 30s window; confidence 0.70 is below the 0.85 fast path)`
5. `INCIDENT_OPENED: candidate accepted: risk confidence 0.71 -> severity medium -> incident created`
6. `CORROBORATED / ESCALATED: candidate corroborates open incident <id> (risk 0.83, severity high, escalated)`

## Debug workflow

```bash
uv run guardianctl debug        # the funnel: Camera→Detection→Tracking→Event→Risk→Notification
tail -f ~/guardian/logs/risk-debug.log            # live decision stream
cat ~/guardian/reports/<incident-id>/timeline.json # replay one incident
```

`guardianctl debug` shows counters at every stage plus rejection reasons
ranked by frequency — the fastest way to see where candidates die.

`timeline.json` contains everything needed to replay a decision: the
incident (risk confidence, severity, review state), every corroborating
event with its frame/detection/track identifiers and signal scores
(ADR-0007 chain intact), the per-frame track evaluations leading up to
it, the risk decisions, and the delivered notification payload.

## Investigating a missed incident

Someone fell but no alert fired. In order:

1. **`guardianctl debug`** — is the funnel alive end to end? Zero
   detections means a camera/model problem, not a risk problem.
2. **Find the track** in `risk-debug.log` around the time of the fall
   (grep the camera id). Confirm a `track #N` existed. If tracks show
   `track not confirmed`, the person was never tracked long enough —
   look at detection quality first.
3. **Read the rejection reasons** on that track:
   - `downward velocity too low` → the drop was slower than the gate, or
     history was interrupted (check `track lost` lines just before).
   - `confidence below threshold` → read the breakdown: which signal
     scored low? A high stillness score requires the person to actually
     stay down for ~1 s; ground contact requires the box to end low in
     the frame (camera angle matters).
   - `detector cooldown active` → a previous candidate on the same track
     already fired within 10 s.
4. **Candidate emitted but no incident?** Look for the risk-side line:
   `awaiting corroboration`, `suppressed after human dismissal`, or
   `confidence below policy minimum` tells you which policy knob applied.
5. **Incident opened but no phone alert?** Check the timeline.json
   `notification` section and `logs/notifications.log`.

Every step has an explicit line — if you cannot find one, that itself is
a bug: file it as a broken invariant ("silent failures are forbidden").

## Cost

Per-frame overhead is one dataclass + one log line per tracked person
(~tens of µs); the debug log rotates at 5 MB × 3 like every subsystem log
and does NOT propagate into system.log. Timeline export happens only when
incidents exist.
