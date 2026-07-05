# ADR-0014: Notification Architecture

- **Status:** Accepted
- **Date:** 2026-07-05
- **Deciders:** Founder, Lead Software Architect

## Context

SafetyIncidents must reach humans reliably, within the charter's < 1 s
budget, **without internet** — the kindergarten's uplink dying must never
mean a fall goes unannounced. Sprint 12 builds the delivery layer; phones,
dashboards, and the cloud backend are explicitly out of scope, so the
design must be honest about what "delivered" means today and leave clean
seams for every transport that comes later.

## Decision

1. **Local-first: delivery means durably on the box.** `LocalPushChannel`
   appends every notification payload to a JSONL outbox with fsync, then
   fans out best-effort to in-process subscribers. Durability is the
   delivery guarantee; live push is opportunistic on top. The device API
   (next sprint) is the transport to directors' phones over the LAN: it
   subscribes for live pushes and serves the outbox for catch-up after
   reconnects — no cloud, no FCM/APNs in the alert path (they may join
   later as *secondary* channels behind the same port).

2. **The engine is an IncidentConsumer.** The sixth layer composed through
   a callable seam (detections → tracks → candidates → incidents →
   notifications); the risk engine and everything above it have no idea
   notifications exist, and the risk engine never touches channels. No AI
   logic, no risk logic inside: the policy reads severity and status only.

3. **Validated lifecycle in the domain.** PENDING → QUEUED → SENDING →
   {DELIVERED | RETRYING → SENDING… | FAILED}; the transition table lives
   in the immutable `Notification`, so an illegal transition — or a
   DELIVERED without a successful attempt, or an out-of-order attempt
   number — is unrepresentable. Every attempt is recorded
   (`DeliveryAttempt`): the delivery history is auditable evidence.

4. **Policy maps severity to urgency, configurably.** Defaults:
   CRITICAL/HIGH → immediate (jump the queue), MEDIUM → standard,
   LOW → ignored. Escalations re-notify by default (a situation that got
   worse is news); resolutions are silent by default (the reviewer already
   knows). Per-incident dedup keeps corroborating snapshots from spamming.

5. **Exponential retry with a hard end.** 1 s → 2 s → 5 s → 10 s → 30 s →
   permanent FAILED (six attempts). Failed notifications leave the queue,
   are counted, and keep their attempt history — silent infinite retry
   hides infrastructure problems; a bounded ladder surfaces them in
   metrics and (later) device health.

6. **Payload is metadata-only, by construction.** ids (notification,
   incident, camera, track, correlation — the ADR-0007 chain survives to
   the wire), severity, confidence, timestamps, event count, and a text
   summary that references people only as track numbers. No images, no
   video, no PII — enforced by the payload builder and asserted by tests.
   Evidence clips remain on-box behind the future device API's
   authenticated review flow (docs/00: video stays inside the kindergarten).

7. **Channels are pluggable and earn their sprints.** One
   `NotificationChannel` port; Webhook/Telegram/SMS/Email exist as
   reserved abstract interfaces only — each remote transport carries its
   own credentials, cost, and privacy review, and none may ship as a
   side effect of this sprint.

## Consequences

- Measured: ~10,700 notifications/s through the engine with an instant
  channel; mean creation→delivered well under a millisecond before
  transport cost — the layer adds nothing perceptible to the 1 s budget.
- "Delivered" today means durably-spooled-locally, not on-a-phone; that is
  the honest maximum without the device API, and the outbox is exactly the
  catch-up mechanism phones will need anyway.
- The outbox grows unboundedly for now; rotation/retention arrives with
  the device API sprint (same place read-offsets appear).
- Queued notifications survive engine stop/start within a process but not
  a crash before spooling; the at-most-one-second exposure window is
  accepted for V1 and shrinks to zero if intake later journals first.

## Alternatives Considered

- **Push straight to FCM/APNs now:** rejected — puts Google/Apple uplinks
  inside the alert path, violating the charter's offline requirement, and
  drags in the forbidden mobile scope.
- **Webhook as the first channel:** rejected — every webhook target is
  off-box infrastructure someone must run; the box must be complete alone.
- **Unbounded retry:** rejected — hides dead transports forever; bounded
  failure is observable failure.
- **Mutable notification with a status setter:** rejected — the validated
  immutable lifecycle is what makes "illegal transitions impossible" a
  property instead of a hope.
