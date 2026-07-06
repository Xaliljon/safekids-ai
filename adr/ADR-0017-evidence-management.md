# ADR-0017: Evidence Management

- **Status:** Accepted
- **Date:** 2026-07-06
- **Deciders:** Founder, Lead Software Architect

## Context

Directors review AI-raised incidents (ADR-0013) from a metadata summary
and a signal timeline. For confident decisions they need to *see* the
moment — but Guardian is explicitly **not** a video recording system
(charter; docs/04). The tension: visual evidence for every safety
incident, with privacy as the highest priority, on a frozen architecture
(camera → vision → tracking → event → risk untouchable), fully offline.

## Decision

1. **A circular RAM buffer, never a recording.** Each camera's last ~30 s
   live as JPEG frames in memory (`FrameRingBuffer`), continuously
   overwritten. Nothing touches disk until the Risk Engine opens an
   incident. The buffer attaches to the existing FrameConsumer seam via
   fan-out in the supervisor; its `on_frame` is a constant-time bounded
   `put_nowait` — when the JPEG-encoder thread falls behind, frames are
   **dropped, never awaited** (a sparser clip beats added AI latency).
   A parallel `TrackRingBuffer` keeps per-frame tracker conclusions
   (tuples of floats — negligible memory) via the TrackConsumer seam.

2. **Incident → asynchronous clip export.** The `EvidenceRecorder` is an
   IncidentConsumer fanned out next to the Notification Engine — the alert
   always fires first and the Risk Engine never waits. A worker thread
   waits out the post-roll (default 15 s), slices [−15 s, +15 s] from the
   ring, and encodes **two variants**: the ORIGINAL clip and the
   AI-ANALYSIS overlay (bounding boxes, track ids, confidence, a clip
   timeline with the incident marker, timestamps) — rendered at export
   time, never on the hot path. Escalations of the same incident do not
   re-export (first alert wins).

3. **An open evidence domain.** `Evidence` carries the full ADR-0007
   identity chain (incident, track, detection, frame, correlation) plus
   status (`PENDING → RECORDING → READY | FAILED → EXPIRED | DELETED`),
   typed clip references and plaintext-safe metadata. `EvidenceType`
   already enumerates future artifacts (snapshot, pose skeleton, heatmap,
   risk timeline, track replay, AI explainability) — **video is only the
   first type**; new types add producers, not architecture.

4. **Storage: separate, encrypted, tombstoned.**
   `$GUARDIAN_HOME/evidence/<incident-id>/` holds `clip.mp4.enc`,
   `clip-overlay.mp4.enc`, `thumbnail.jpg.enc` and `metadata.json` — never
   mixed with logs or models. Media is AES-256-GCM encrypted in memory
   before it touches disk (no plaintext clips, and GCM makes tampering
   fail loudly); the key lives apart under `data/keys/evidence.key`
   (0600). `metadata.json` stays plaintext deliberately: identifiers and
   clip facts only (no pixels), so retention can sweep without the vault.

5. **Retention: nothing lives forever.** Defaults — dismissed 24 h,
   confirmed 30 d, pending 30 d, **critical 90 d regardless of outcome**.
   A sweeper thread enforces expiry; the Device API's resolve route
   updates the evidence's incident status so the right lifetime applies
   the moment a human decides. Deletion is secure (random overwrite +
   unlink — wear-leveling caveat documented; full-disk encryption is the
   provisioning layer's roadmap) and leaves a metadata tombstone so the
   audit trail stays whole. Manual deletion uses the same path.

6. **Device API is the only door.** Four endpoints
   (`/evidence`, `/evidence/{id}`, `/evidence/{id}/video?variant=`,
   `/evidence/{id}/thumbnail`), all Bearer-token gated to paired trusted
   devices; media decrypts to memory per request and is served with
   `Cache-Control: no-store`. **Every access is audited** to
   `evidence/audit.jsonl` (who, what, when, which variant). There is no
   sharing, no export, no cloud path — by construction.

7. **The app reviews; it never redistributes.** Flutter shows the
   evidence inside incident review (Incident → Video → AI signals →
   Timeline → Review → Decision), with an Original / AI-analysis switch,
   thumbnail poster, download progress and a size-bounded LRU offline
   cache. Playback controls only (play/pause/replay/fullscreen) — no
   editing, no share sheet, nothing leaves the app.

## Consequences

- Directors see exactly what the AI saw — both raw and annotated — for
  every incident, entirely on the LAN, with the alert path untouched
  (fan-out costs one enqueue).
- Privacy holds by construction: no continuous recording (RAM ring),
  no plaintext at rest (AES-256-GCM), no unaudited access, no sharing
  surface, guaranteed expiry.
- Memory cost ≈ 30 MB per camera (30 s × 10 fps × ~100 KB JPEG); export
  cost is bounded and runs on one background thread.
- Recovery: a recorder crash marks the record FAILED (the app explains it
  honestly); shutdown mid-post-roll exports what the ring holds; the
  watchdog (ADR-0016) restarts the recorder and ring threads.
- Accepted gaps for pilot: LAN-plaintext transport (same as ADR-0015),
  key file relies on box filesystem permissions until full-disk
  encryption ships, `metadata.json` reveals incident timing (not imagery).
- Explicitly out of scope: cloud storage, live streaming, RTSP playback,
  continuous recording, editing, parent access, analytics.
