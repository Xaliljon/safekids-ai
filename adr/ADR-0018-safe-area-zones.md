# ADR-0018: Safe-Area Zones and Zone-Exit Candidates

- **Status:** Accepted
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
   everything.** Under-alerting is the one unacceptable failure mode;
   over-alerting costs a director one glance at a pending item (ADR-0013's
   stance, and the app's own "CRITICAL always alerts" rule).

6. **Trust is about provenance, not precision — drift is not the risk.**
   The obvious fear, a box offline for weeks, is arithmetically a
   non-problem: an uncompensated crystal drifts ≤ 50 ppm ≈ 4.3 s/day, so a
   month unsynchronized costs ~2 minutes against windows measured in
   hours. Distrusting such a box would disable schedules for a fault too
   small to move a boundary. The failures that *do* move a boundary are
   categorical, and a clock is trusted unless one of them holds:

   - **Never set.** No external synchronization has been observed since
     the box was provisioned. A cold boot without an RTC lands at the
     systemd epoch, not at "now".
   - **Went backwards.** `now()` is earlier than a persisted high-water
     mark the box writes periodically (atomically, temp + rename — the
     ADR-0009 pattern). Time running backwards means the clock was reset,
     whatever it currently reads.
   - **No local zone.** A wall-clock window is meaningless without a
     configured timezone, so an unset zone is a fault, not a default.

   Provenance is read from systemd's time-sync interface. ADR-0016 already
   makes systemd a platform assumption (`deploy/guardian-edge.service`);
   an interface that cannot be read reports `unknown`, which is untrusted,
   which enforces.

7. **Staleness widens window edges instead of disabling schedules.** A
   trusted-but-stale clock carries an explicit error bound —
   `50 ppm × time since last synchronization` — and a zone is treated as
   active whenever the frame's local time falls *within that bound of a
   window edge*. A box offline for 70 days has a ±5-minute bound and so
   enforces its nap-room zone from 12:55 rather than 13:00; a box offline
   for a year enforces from 12:34. Degradation is proportional, always in
   the safe direction, and needs no arbitrary "trust expires after N days"
   constant. Ambiguous local times — a window edge inside a DST gap or
   repeat — resolve the same way: active.

8. **Clock status is a first-class operational signal.** `ops/clock.py`
   exposes it; `guardianctl diagnose` and `/health` report trusted/untrusted
   with the reason and the current error bound; `deploy/install.sh`
   validates that a timezone is configured before a box is handed over.
   None of this exists today and all of it is in scope for this feature —
   a schedule whose clock nobody checks is the silent failure this ADR is
   trying not to build.

9. **Absence is never evidence.** The detector reasons only over CONFIRMED
   observations, exactly as ADR-0012 §4 requires. A track that vanishes —
   occluded, lost, or out of frame — produces no candidate, ever. The child
   who walks out through a doorway is caught by *where the polygon is
   drawn*, not by inferring from disappearance: **the safe-area boundary
   must sit inside the frame with visible margin on every exit route.**
   That is a requirement this ADR imposes on deployment, and the drawing
   tool must state it.

10. **A candidate requires sustained, unambiguous exit:** the track must be
    continuously outside the polygon for `min_dwell_seconds` (**default 10
    seconds**, set by the founder as a product statement about how long an
    unattended child is acceptable), and beyond a `boundary_margin` past the
    edge. The margin is hysteresis — a child standing on the line must not
    oscillate — and the dwell turns "stepped over briefly" into "is out
    there". Both are hard gates; neither is a weighted signal.

11. **Confidence stays explainable and combines the same way falls do:**
    dwell duration, distance past the boundary, and the exit's motion
    consistency (a track that walked out, not one that teleported by a
    detection glitch) each score in `[0, 1]` and combine by weight, above a
    threshold, with a per-track cooldown. Every candidate carries its
    `EventSignal`s — the domain refuses one that does not (ADR-0012 §1) —
    and every rejection carries its reason through the existing evaluation
    observer, including "this zone is not active at 09:14".

12. **Zones live in `$GUARDIAN_HOME/config/zones.yaml`, not in
    `cameras.yaml`.** Different lifecycle, different author: `cameras.yaml`
    holds credential references and is written once by an integrator, while
    zones and their hours are redrawn whenever furniture or the daily
    routine moves. Keeping them apart means the zone editor never opens the
    file that references secrets.

13. **Zones are drawn, not typed.** `guardianctl zones` serves a local page
    showing the camera's current frame and records the clicked polygon and
    its hours — the same local-web-editor pattern the dataset annotator
    already uses (`ai/guardian_ai/acquisition/annotator/`). Hand-writing
    coordinates into YAML is a supported escape hatch, not the path. This
    is an installer-time task, not a director's daily task.

14. **`CandidateEventType.ZONE_EXIT` gets its own `RiskPolicy`, and a
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
  schedules, a wrong clock produced wrong timestamps; now it decides
  whether a boundary is enforced. Decisions 5–8 make every failure
  direction safe, at the cost of a box with a broken or never-set clock
  enforcing every zone around the clock and saying so loudly in
  diagnostics. That is the intended trade.
- **A cold boot without an RTC is the most likely way to reach "never
  set".** Software cannot fix this; a real-time clock with a battery in
  the BOM can. This ADR recommends one to `hardware/` for the next Edge
  Box revision — it is cheap, and it turns the worst clock fault from
  likely-on-every-power-cut into rare.
- **Trust is per box, not per zone**, so one clock fault enforces every
  scheduled zone at once. Correct, and worth stating: an operator seeing
  "all my nap-room alerts came back" should find one clock warning in
  diagnostics, not hunt through zones.
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
- **"Distrust the clock after N days without sync":** rejected — every
  candidate N is arbitrary, and the arithmetic says the honest N is
  enormous (a year of drift is ~26 minutes). A hard threshold would either
  fire far too early, disabling schedules on a healthy offline box, or sit
  so far out that it never fires and only looked like a safeguard. The
  error bound in Decision 7 is the same idea without the invented number.
- **Parsing a specific NTP daemon's output** (chrony, ntpd, timesyncd):
  rejected — it makes the safety path depend on which daemon an image
  happens to ship and on text formats that change. systemd's interface is
  already a stated platform assumption; anything unreadable degrades to
  untrusted, which is safe by Decision 5.
- **Correcting the clock from camera RTSP/RTCP timestamps:** rejected —
  cameras are untrusted devices (docs/03: never trust external devices),
  and letting one set the box's notion of time hands a safety decision to
  the least controlled component on the network.

## Decided in Review (2026-08-14)

Three questions were put to the founder before this ADR could be finished:

1. **Restricted zones in V1?** No. Safe zones only (Decision 3).
2. **Do zones need schedules?** Yes (Decisions 4–8) — this is the change
   that pulled clock trust into scope.
3. **Default `min_dwell_seconds`?** 10 seconds (Decision 10).

The engineering question schedules opened — what makes a clock trustworthy
on a box that may run offline for weeks — is answered in Decisions 6–8.
The short version: the framing was wrong. Drift is not the risk, because a
month offline costs about two minutes against windows measured in hours.
The risks are categorical (never set, ran backwards, no timezone), and
what remains after them is a bound, not a verdict.

Nothing in this ADR is open. What it hands to other components: an RTC
with a battery to `hardware/` for the next revision, and a timezone check
to `deploy/install.sh` before any box with scheduled zones ships.
