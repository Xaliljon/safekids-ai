# ADR-0011: Multi-Object Tracking (ByteTrack)

- **Status:** Accepted
- **Date:** 2026-07-05
- **Deciders:** Founder, Lead Software Architect

## Context

Every SafeKids V1 event needs temporal identity, not per-frame detections:
fall detection reasons about *one child's* box over time, zone-exit about
*one person* crossing a boundary, and alert evidence must say "this child,
these ten seconds". Sprint 9 adds tracking between detection and the
future risk engine, without touching capture (Sprint 2) or the inference
runtime (Sprint 4).

## Decision

1. **Algorithm: ByteTrack, implemented in-house, dependency-free.** The
   published algorithm (Zhang et al.) with its defining idea — low-
   confidence detections *rescue* occluded tracks instead of being thrown
   away — implemented as ~250 lines of our own code over a constant-
   velocity Kalman filter. No tracker package dependency: reference
   implementations pull in the AGPL-adjacent YOLOX training stack or
   unmaintained wrappers, and the algorithm is small enough to own, test,
   and later port to the Jetson.

2. **Tracking is an optional stage of the vision pipeline.** The pipeline
   gains `tracker`, `track_consumer`, and `track_overlay_renderer` ports;
   with no tracker configured, behavior is bit-identical to Sprint 8.
   The tracker runs on the pipeline's single worker thread (per-camera
   state, no locking), and a tracker failure loses that frame's tracking
   only — detections still flow, counted in `PipelineStats.tracker_errors`.
   The risk engine attaches as a `TrackConsumer`, symmetric with
   `DetectionConsumer` (ADR-0006 §4).

3. **Track lifecycle: TENTATIVE → CONFIRMED → LOST → REMOVED.** New tracks
   are TENTATIVE until `confirm_after` hits (default 3) so single-frame
   false positives never surface; CONFIRMED tracks that miss a frame go
   LOST and coast on Kalman prediction for up to `max_lost_frames`
   (default 30) before REMOVED. Downstream consumers act on CONFIRMED
   (`TrackingResult.confirmed()`).

4. **Dual identity per track, ADR-0007 preserved end-to-end.** Each track
   carries a `track_id` UUID (minted at track birth, stable for life) and
   a short `display_id` int for overlays and logs. Every `Track` embeds
   the full `Detection` that last evidenced it, and `TrackingResult`
   propagates the source frame's `frame_id`/`correlation_id` unchanged —
   an alert will trace from notification through track to the exact
   captured frame.

5. **Deliberate simplifications, recorded here:**
   - *Greedy IoU association instead of Hungarian* — avoids a scipy
     dependency on the box; at classroom object counts the assignment
     difference is negligible, and the matcher is one function behind the
     same signature if profiling ever disagrees.
   - *Label-aware association* — a `child` track can never be continued by
     a `chair` detection; identity mistakes are worse than fragmented
     tracks in a safety system.
   - *No appearance embeddings (ReID)* — ByteTrack's motion-only
     association is the paper's own configuration; embeddings would add a
     second model to every frame for marginal gain at fixed-camera,
     classroom-density scenes.

## Consequences

- Measured: p50 0.15 ms / p95 0.17 ms per frame with 12 objects — tracking
  is noise next to ~15 ms inference; the 62 FPS end-to-end figure holds.
- Track ids are stable through occlusions up to `max_lost_frames`; longer
  disappearances produce a new identity. Re-identification across long
  gaps is explicitly out of scope until a real need appears.
- Kalman state lives in normalized coordinates, so tracking is resolution-
  independent like everything else (ADR-0006 §2).
- The fall-detection engine gets what it needs: per-child box history via
  stable ids with human-verifiable evidence chains.

## Alternatives Considered

- **Depend on a ByteTrack/supervision package:** rejected — license
  entanglement risk, unmaintained wrappers, and a core safety component
  should not be a black box (docs/03: never trust external code with
  safety-critical state we can own in 250 lines).
- **SORT (high-confidence only):** rejected — ByteTrack's low-score rescue
  is precisely what survives partial occlusion in crowded classrooms; SORT
  fragments tracks exactly when children cluster.
- **Tracker as a detection consumer outside the pipeline:** rejected —
  overlays could not show track ids (consumers see no pixel buffers), and
  every downstream consumer would need its own tracker instance.
- **Hungarian assignment (scipy):** deferred, see §5 — swap-in is one
  function if greedy ever measurably fragments tracks.
