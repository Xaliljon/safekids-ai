# Notification Engine

- **Date:** 2026-07-05 (Sprint 12)
- **Reflects:** ADR-0014 (notification architecture), ADR-0013 (risk engine), ADR-0007 (identity)
- **Scope:** incident → notification delivery; no phones, no backend, no remote transports

## Purpose

Converts SafetyIncidents into reliably delivered, metadata-only
notifications. **Local-first** (ADR-0014): delivery means durably on the
box; the internet is never in the alert path.

```
… → RiskEngine ──IncidentConsumer──> NotificationEngine ──NotificationChannel──> LocalPushChannel
                                          │                                        │  durable JSONL outbox (fsync)
                                     policy + dedup                                └─ live fan-out → (device API, later)
                                     queue + retry ladder
```

The engine is the sixth layer attached through a callable seam. Upstream
components do not know notifications exist; the risk engine never touches
channels; there is no AI or risk logic here.

## Domain (`domain/notification.py`) — all immutable

| Object | Role |
|---|---|
| `Notification` | metadata-only message; lifecycle transitions only via validating methods |
| `NotificationStatus` | PENDING → QUEUED → SENDING → {DELIVERED \| RETRYING → SENDING… \| FAILED}; illegal transitions **unrepresentable** |
| `NotificationPriority` | IMMEDIATE (jumps the queue) / STANDARD |
| `NotificationPolicy` | severity → action mapping + escalation/resolution switches |
| `DeliveryAttempt` | audited record of every try (number, channel, timing, error) |

## Policy (defaults; fully configurable)

| Severity | Action |
|---|---|
| CRITICAL | notify, immediate |
| HIGH | notify, immediate |
| MEDIUM | notify, standard |
| LOW | ignored |

Dedup: one notification per incident snapshot state — corroborations are
silent, **escalations re-notify** (default on), resolutions are silent
(default off).

## Retry (`application/notifications/retry.py`)

Failed sends climb the ladder **1 s → 2 s → 5 s → 10 s → 30 s → permanent
FAILED** (six attempts). Failed notifications leave the queue with their
full attempt history; nothing retries forever.

## Payload — metadata only, never media, never PII

`notification_id, incident_id, camera_id, track_id, track_display_id,
correlation_id, type, severity, confidence, incident_status, timestamp,
created_at, summary, event_count, priority` — the ADR-0007 chain survives
to the wire; people appear only as track numbers. Tests assert the exact
field set and the absence of media/PII keys. Evidence clips stay on-box
for the authenticated review flow (future device API).

## LocalPushChannel (`infrastructure/notifications/local_push.py`)

Durable JSONL outbox (`notifications.jsonl`, fsync per line) + best-effort
fan-out to in-process subscribers. Spool failure = delivery failure
(engine retries); subscriber failure never is. The device API will
subscribe for live pushes and serve the outbox for phone catch-up.
Webhook/Telegram/SMS/Email exist as reserved abstract interfaces only.

## Metrics (backend-independent snapshot)

queue size, created / ignored-by-policy / duplicates-suppressed,
delivered, permanently failed, retry count, success/failure attempt
counts, last & mean send latency, mean creation→delivered time.

## Measured

~**10,700 notifications/s** through the engine (instant channel);
creation→delivered well under 1 ms before transport cost. 41 new tests,
97% coverage over the new modules (100% on the engine and channel;
the uncovered lines are the reserved abstract interfaces).

## Failure handling summary

| Failure | Behavior |
|---|---|
| channel send fails | attempt recorded → retry ladder → permanent FAILED after 6 attempts |
| spool unwritable | ChannelDeliveryError → same retry path |
| listener raises | logged, observation dropped, delivery unaffected |
| subscriber raises | logged, other subscribers still served, delivery unaffected |
| engine stopped | queue retained for restart; no incidents lost while attached upstream |

## Out of scope (later)

Device API (LAN transport to phones, outbox offsets/rotation), Flutter
app, backend sync, remote channels (each behind the existing port, each
with its own privacy review), `contracts/events` wire schema formalization.
