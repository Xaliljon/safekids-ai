# Safe-Area Zones and Zone Exit

- **Date:** 2026-08-14
- **Reflects:** ADR-0018 (zones and clock trust), ADR-0012 (event engine), ADR-0006 (normalized coordinates)
- **Scope:** the charter's V1 event #2 — "Child Leaves Safe Area". Safe zones only; restricted zones and cry detection are not built.

## Purpose

Lets an operator declare **where safety ends** on each camera, and raises a
candidate when a child is sustained outside it. The declaration is a
polygon plus optional hours; everything else is the same machinery falls
already use — a `CandidateDetector` behind the same port, weighted
explainable signals, and a human who decides what is true (docs/04).

## Position in the chain

```
ByteTrack ──TrackConsumer──> EventEngine ──> [PotentialFallDetector, ZoneExitDetector] ──> RiskEngine
                                                          ▲
                                    zones.yaml ───────────┤
                                    ClockTrust ───────────┘  (may the hours be honoured?)
```

Adding the second detector changed no engine: `EventEngine` already fans
out over a list. What it did change is that the box's **clock entered the
safety path** for the first time.

## Components

| Module | Responsibility |
|---|---|
| `domain/zone.py` | `Zone` (polygon, point-in-polygon, distance to boundary), `ScheduleWindow` (days + local wall-clock window, wrapping past midnight), `Weekday`. Pure geometry and calendar; refuses a polygon that encloses nothing. |
| `infrastructure/zones/config.py` | Loads `zones.yaml` strictly. A malformed zone is refused loudly — a safe area that quietly lost a vertex still looks like a safe area. |
| `ops/clock.py` | `ClockTrust`/`ClockStatus`: is local wall-clock time trustworthy, and by how much could it be wrong. |
| `application/events/zone.py` | `ZoneExitDetector`: schedule gate, cooldown, inside/margin gates, dwell accumulation, weighted confidence, full decision explanations. |
| `application/risk/policy.py` | The `ZONE_EXIT` policy — same single-candidate opening as falls, longer dismissal suppression, slower severity climb. |

## The zone-exit heuristic

Position is the bounding box's **bottom-centre**: where a standing child
meets the floor, and the floor is what the polygon describes.

| Gate (hard) | Rule |
|---|---|
| Schedule | The zone must exist at the frame's local time — unless the clock is untrusted, which enforces everything |
| Inside | A child inside the polygon (boundary counts as inside) is never a candidate |
| Margin | Must be > `boundary_margin` (0.02) past the edge — hysteresis, so standing on the line does not oscillate |
| Dwell | Must be continuously outside for `min_dwell_seconds` (**10 s**, a founder decision about how long an unattended child is acceptable) |

| Signal | Measurement | Weight |
|---|---|---|
| `dwell_outside` | continuous seconds outside, saturating at 30 s | 0.50 |
| `distance_past_boundary` | normalized distance beyond the edge, saturating at 0.15 | 0.30 |
| `observation_consistency` | `1 − largest gap ÷ dwell` — a stretch watched continuously beats one bridged by a blink | 0.20 |

Dwell is held **per (track, zone) in the detector**, not derived from
`TrackHistoryStore`: the shared history keeps ~6 seconds while the gate is
measured in tens, so deriving it would silently cap the dwell at whatever
the buffer happened to hold. Per-track state is pruned once the track has
been gone longer than the cooldown.

## Absence is never evidence

A track that vanishes — occluded, lost, or out of frame — produces
**nothing**, ever, and a gap longer than `max_gap_seconds` (1.5 s)
restarts the dwell rather than bridging it. The child who walks out
through a doorway is caught by *where the polygon was drawn*, which is why
`zones.example.yaml` states the deployment requirement in full: the
boundary must sit inside the frame with visible margin on every exit
route. This is the one place where the feature depends on the installer
rather than the algorithm, and it is deliberate — the alternative promotes
absence of evidence to evidence, and makes every cupboard a false alarm.

## Clock trust (`ops/clock.py`)

Schedules can only ever *suppress*, so the failure direction must be
over-alerting. Trust is binary and rare:

| Fault | Meaning |
|---|---|
| Never set | no external synchronization since provisioning — a cold boot without an RTC starts at the system epoch |
| Ran backwards | `now()` precedes the persisted high-water mark; the clock was reset, whatever it reads |
| No timezone | a wall-clock window cannot be evaluated without one |

Anything else is trusted. **Drift is not a fault**: at ≤ 50 ppm
(4.32 s/day) a month offline costs ~2 minutes against windows measured in
hours. Staleness instead carries an error bound that *widens* every window
edge — 70 days offline enforces a 13:00 zone from 12:55, a year from
12:34. DST gaps and repeats resolve the same way: active.

`/health` reports `clock` and `zones`; a box whose scheduled zones are
being enforced regardless of hours says so instead of looking healthy.

## Verified (73 new tests)

Geometry including concave (L-shaped) rooms and boundary points;
overnight and multi-window schedules; margin widening that may never
narrow; the three clock faults and the error bound (including the ADR's
70-day worked example); high-water-mark persistence and corruption; every
gate; dwell restart on re-entry and on observation gaps; cooldown; state
pruning; strict config loading; and the shipped example file actually
loading.

## Out of scope (later)

`guardianctl zones` (the drawing UI — YAML is the documented escape hatch
until it exists), automatic scene-drift detection when a camera moves,
cross-camera fusion at overlapping view seams, restricted zones, and real
floor calibration — which is what finally retires both this feature's
image-space distances and ADR-0012's ground-proximity proxy.
