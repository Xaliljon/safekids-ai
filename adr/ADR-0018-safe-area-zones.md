# ADR-0018: Safe-Area Zones and Zone-Exit Candidates

- **Status:** Proposed
- **Date:** 2026-08-14
- **Deciders:** Founder, Lead Software Architect

## Context

"Child Leaves Safe Area" is the second of the charter's three V1 events and
the only one not blocked on a missing PRD. The event engine was built to
accept it: `CandidateDetector` is a list, per-track history already exists,
and ADR-0012 named zone-exit as future work behind the same port. What does
*not* exist is the thing a zone detector needs and a fall detector does
not — a **declaration of where safety ends**, drawn per camera by a human,
plus the vocabulary and policy to carry the new event type end to end.

Four forces shape this decision:

1. A zone is a statement about the *floor*, but the box sees *pixels*.
   ADR-0012 already accepted an image-space proxy for ground proximity and
   flagged per-camera calibration as a planned config input. This ADR is
   where that debt comes due.
2. "The child is no longer visible" and "the child left" are different
   facts that look identical to a tracker. Conflating them either spams
   directors on every occlusion or misses the child who actually walked
   out — the second is unacceptable, the first destroys trust (docs/13).
3. A safe area is not a permanent fact. The nap-room boundary at 13:00 is
   not the boundary at 09:00, and the founder confirmed in review that
   kindergartens need this. A zone therefore has a *when*, and a "when"
   that silently stops enforcing is a safety hazard of its own.
4. A zone is the first piece of *deployment-specific safety configuration*
   in the product. Getting it wrong is silent: a mis-drawn polygon looks
   exactly like a correct one until a child is missed.

## Decision

1. **A zone is a polygon in normalized image coordinates, owned by one
   camera.** Vertices are `[0, 1]` pairs in the same coordinate space the
   whole vision stack already uses (ADR-0006 §2: normalized, top-left
   origin), so a zone needs no resolution, no lens model, and no
   homography. This is deliberately the *weak* geometric model — see
   Consequences; it is chosen because it is the only one an installer can
   produce and verify by looking at one still frame, and because every
   other signal in the event engine already lives in this space.

2. **A track's position is its bounding box's bottom-centre.** That is
   where a standing person meets the floor, and the floor is what the
   polygon describes. Box centres put a child "inside" while their feet
   are across the line.

3. **V1 declares safe zones only.** A candidate is raised for a track
   *outside* the polygon. Restricted zones ("never near the stairs") are
   the same geometry with the test inverted, and the founder declined them
   for V1 in review — so they are not built. The charter names one event;
   we build one event.

4. **A zone may declare when it exists.** `active_windows` is a list of
   `{days, from, to}` entries in local wall-clock time; a zone with no
   windows exists always. Outside its windows a zone is *not part of the
   scene* — the nap-room boundary at 09:00 describes furniture that is not
   there — so the detector measures against the zones that exist at the
   frame's timestamp and nothing is suppressed after the fact.

   - **The frame's own `captured_at` decides, never `now()`.** Frames carry
     tz-aware UTC (`rtsp_stream.py`), converted to the box's local zone at
     evaluation. Replaying a recorded timeline through the debug recorder
     must reproduce the same decision.
   - **Windows wrap past midnight** (`from > to`), the same rule the app's
     quiet hours already implement (`SettingsController.isQuietAt`).
     Operators should meet one time model in this product, not two.

5. **A schedule may only ever suppress, so an untrustworthy clock enforces
   everything.** If the box cannot establish trustworthy local time — no
   NTP since boot, an implausible clock, no configured timezone — every
   scheduled zone is treated as active. Under-alerting is the one
   unacceptable failure mode; over-alerting costs a director one glance at
   a pending item (ADR-0013's stance, and the app's own "CRITICAL always
   alerts" rule). **This requires a clock-trust check that does not exist
   today:** `guardianctl diagnose` and `/health` must report clock and
   timezone status, and the runtime must expose it to the detector. That
   check is in scope for this feature, not a follow-up.

6. **Absence is never evidence.** The detector reasons only over CONFIRMED
   observations, exactly as ADR-0012 §4 requires. A track that vanishes —
   occluded, lost, or out of frame — produces no candidate, ever. The child
   who walks out through a doorway is caught by *where the polygon is
   drawn*, not by inferring from disappearance: **the safe-area boundary
   must sit inside the frame with visible margin on every exit route.**
   That is a requirement this ADR imposes on deployment, and the drawing
   tool must state it.

7. **A candidate requires sustained, unambiguous exit:** the track must be
   continuously outside the polygon for `min_dwell_seconds` (**default 10
   seconds**, set by the founder as a product statement about how long an
   unattended child is acceptable), and beyond a `boundary_margin` past the
   edge. The margin is hysteresis — a child standing on the line must not
   oscillate — and the dwell turns "stepped over briefly" into "is out
   there". Both are hard gates; neither is a weighted signal.

8. **Confidence stays explainable and combines the same way falls do:**
   dwell duration, distance past the boundary, and the exit's motion
   consistency (a track that walked out, not one that teleported by a
   detection glitch) each score in `[0, 1]` and combine by weight, above a
   threshold, with a per-track cooldown. Every candidate carries its
   `EventSignal`s — the domain refuses one that does not (ADR-0012 §1) —
   and every rejection carries its reason through the existing evaluation
   observer, including "this zone is not active at 09:14".

9. **Zones live in `$GUARDIAN_HOME/config/zones.yaml`, not in
   `cameras.yaml`.** Different lifecycle, different author: `cameras.yaml`
   holds credential references and is written once by an integrator, while
   zones and their hours are redrawn whenever furniture or the daily
   routine moves. Keeping them apart means the zone editor never opens the
   file that references secrets.

10. **Zones are drawn, not typed.** `guardianctl zones` serves a local page
    showing the camera's current frame and records the clicked polygon and
    its hours — the same local-web-editor pattern the dataset annotator
    already uses (`ai/guardian_ai/acquisition/annotator/`). Hand-writing
    coordinates into YAML is a supported escape hatch, not the path. This
    is an installer-time task, not a director's daily task.

11. **`CandidateEventType.ZONE_EXIT` gets its own `RiskPolicy`, and a
    missing one is loud.** The type is named `zone_exit` to match the
    architecture docs that already anticipate it. Registering a detector
    without its policy makes the risk engine drop every candidate; the box
    now reports `risk: degraded` with `ignored_no_policy` when that
    happens, so the misconfiguration is visible instead of silent.

## Consequences

- **Image-space zones are only valid while the camera does not move.** A
  bumped or re-aimed camera silently relocates the safe area. Mitigation
  here is minimal and honest: each zone records `calibrated_at` and the
  stream resolution it was drawn against, `guardianctl diagnose` reports
  zones whose camera resolution has changed, and the pilot handbook makes
  re-drawing part of any camera adjustment. **Automatic scene-drift
  detection is not solved here** and should get its own ADR before this
  feature reaches more than pilot deployments.
- **The box now has a safety-relevant dependency on its clock.** Before
  schedules, a wrong clock produced wrong timestamps; now it could change
  whether a boundary is enforced. Decision 5 makes the failure direction
  safe, but it also means a box with a bad clock will over-alert on
  scheduled zones — visibly, via diagnostics, which is the intended
  trade.
- **The schedule sits in the event layer, not in risk policy.** ADR-0012
  keeps detectors as pure evidence producers and ADR-0013 puts deployment
  rules in policy, so this is a real tension. It is resolved toward the
  zone because a zone's hours are inseparable from the zone itself: split
  across two files, they would drift, and a director who edits the nap
  window while enforcement stays put is exactly the silent failure this
  ADR exists to prevent. Revisit if a second kind of schedule appears.
- **Zones are per camera, and tracking identity is per camera (ADR-0011
  §2: per-camera tracker state).** A child walking from camera A's view
  into camera B's is, to camera A, a child who left. Overlapping-view
  deployments will see false positives at the seams until cross-camera
  fusion exists. Deliberately deferred: fusion is a much larger decision,
  and the failure mode here is an extra pending item, not a missed child.
- **A child who falls just outside the boundary produces two candidates**,
  one per detector, and the risk engine keeps them as two incidents (its
  correlation key includes the event type). This is correct: both
  statements are true, and choosing which one "really" happened is the
  human's job (docs/04).
- **Bottom-centre is a poor floor proxy for a non-upright person.** A lying
  child's box bottom is their side, not their feet. The dwell gate absorbs
  most of this; it remains a known inaccuracy of the same family as
  ADR-0012's ground-proximity proxy, and both are retired by the same
  future work — real floor calibration.
- Zones add no new data to any payload: a candidate still carries ids,
  scores, and geometry, never images or identity (docs/03).
- `contracts/events` must mirror the widened `CandidateEventType` when
  events first cross the device boundary — the same flag ADR-0012 and
  ADR-0013 already raised, now with a second type to make it concrete.

## Alternatives Considered

- **Homography-calibrated floor zones (metric ground plane):** the
  technically correct model, and rejected for V1 — it requires a
  calibration ritual (known reference distances per camera) that a
  kindergarten installer cannot reliably perform, to buy accuracy the
  dwell/margin gates mostly provide. The polygon representation does not
  block it: calibration would change how a point maps to the floor, not
  what a zone is.
- **Rectangles instead of polygons:** rejected — real safe areas are
  L-shaped rooms, mats with a doorway cut out, and playground corners.
  Rectangles would force operators to approximate, and every approximation
  is a place a child is either missed or falsely flagged.
- **Treating track loss near the boundary as an exit:** rejected — it makes
  every cupboard, doorframe, and adult body a false alarm, and it promotes
  *absence of evidence* to evidence, which ADR-0012 §4 forbids for exactly
  this reason.
- **Firing the moment the boundary is crossed (no dwell):** rejected — the
  boundary is a line in a noisy detection space; without hysteresis a child
  playing at the edge generates a stream of candidates and the director
  learns to ignore the app.
- **Cron expressions or iCalendar RRULE for schedules:** rejected — the
  full expressiveness buys nothing a kindergarten timetable needs, and
  every operator who must read one to know whether a child is watched is
  an operator who can misread it. Weekday-plus-window is legible at a
  glance.
- **Schedules in UTC:** rejected — a nap window is a wall-clock fact.
  Storing UTC would make a correct config wrong twice a year.
- **Failing *off* when the clock is untrustworthy** (treat scheduled zones
  as inactive): rejected — it converts a clock problem into a silently
  unwatched child, which is the one failure this product may not have.
- **Suppressing scheduled zones in the risk engine instead** (detector
  always emits, policy filters by time): a genuinely defensible layering,
  and rejected because `RiskPolicy` is per event *type* while a schedule
  is per *zone* — the nap room and the playground need different hours.
  Keying a per-zone map inside a per-type policy would scatter one
  operator concept across two files.
- **Drawing zones in the director's mobile app:** rejected for V1 — precise
  polygon work on a phone is poor, and zone drawing is an installation
  activity performed once beside the camera. Reconsider when the app gains
  a tablet layout.

## Decided in Review (2026-08-14)

Three questions were put to the founder before this ADR could be finished:

1. **Restricted zones in V1?** No. Safe zones only (Decision 3).
2. **Do zones need schedules?** Yes (Decisions 4 and 5) — this is the
   change that pulled clock trust into scope.
3. **Default `min_dwell_seconds`?** 10 seconds (Decision 7).

Still open, and engineering's to answer before implementation: what
constitutes a trustworthy clock on a box that may run for weeks offline,
and therefore what Decision 5's diagnostic actually measures.
