# ADR-0015: Device API and Mobile Integration

- **Status:** Accepted
- **Date:** 2026-07-05
- **Deciders:** Founder, Lead Software Architect

## Context

Sprint 13 puts the first SafetyIncident on a director's phone. The charter
constraints are absolute: fully offline-capable, no cloud, no Firebase/
FCM/APNs, everything on the kindergarten LAN. The phone must never touch
the engines directly, must survive Wi-Fi loss without losing a single
notification, and trust must be establishable by a human standing next to
the box — no accounts.

## Decision

1. **The Device API is the box's only surface** (`guardian_edge/api/`):
   pure composition over existing components — it *subscribes* to
   LocalPushChannel for live push, *reads* the durable outbox for catch-up,
   and *forwards* confirm/dismiss to the RiskEngine review API. No engine
   was modified; none knows the API exists.

2. **Protocol v1: JSON over plain HTTP + WebSocket, two ports** (8787 API,
   8788 WS). Boring transports every client stack speaks; no aiohttp-class
   framework for four endpoints. TLS with box-local certificates is the
   single accepted gap for pilot (trusted kindergarten LAN) and is tracked
   for the hardening sprint.

3. **Pairing = code on the box, token on the phone.** The box shows a
   6-digit single-use code (today: logs; the device will display it); the
   phone exchanges it for a long-lived random token, persisted on both
   sides (box: trusted_devices.json; phone: Hive). Trust is local,
   explicit, per-device, human-granted — and revocable by deleting the
   state file. No accounts, no cloud identity. mDNS discovery is planned;
   manual IP entry ships first and remains the fallback forever.

4. **Missed-notification sync is a line cursor over the outbox.** The
   ADR-0014 outbox turns out to be exactly the catch-up mechanism:
   the phone remembers how many lines it has seen; reconnect = fetch
   `?after=N`, then stream live. Live WS frames advance the cursor by one
   each — the phone can never double-count or miss a line.

5. **The app is offline-first with the box as the only source of truth.**
   Everything renders from the Hive cache; connectivity only *refreshes*
   it. Incident status changes exclusively via box responses — the app
   never mutates incidents locally (docs/04: the review record lives where
   the incident lives). The connection loop reconnects forever with a
   cancellable backoff.

6. **Flutter architecture per ENGINEERING.md, no new patterns:** Riverpod
   (state/DI), GoRouter (created once — navigation never resets on
   rebuilds), Dio (HTTP), web_socket_channel (WS), **Hive** for local
   storage (of the mandated Hive/Isar pair: pure Dart, no codegen, trivial
   to test; revisit Isar if the local schema outgrows JSON maps). Shared
   models live in `guardian_core` — strict wire parsing, unknown values
   fail loudly.

## Consequences

- The deliverable chain works end-to-end on a LAN with the internet
  unplugged: box → device API → WS → notification center → details →
  confirm/dismiss → risk engine records the named device as reviewer.
- Plain HTTP on the LAN is the accepted pilot risk; the pairing token
  gates every endpoint and the WS handshake, and evidence media never
  transits (payloads are ADR-0014 metadata-only).
- The outbox cursor couples the phone to outbox line numbering; outbox
  rotation (future) must version the cursor or reset it explicitly.
- One WS server broadcast set serves all paired devices; per-device
  filtering (e.g. role-based) is a policy layer for later.

## Alternatives Considered

- **FCM/APNs for push:** forbidden by the sprint and the charter — a
  cloud dependency in the alert path breaks offline operation.
- **mDNS-only discovery:** rejected — mDNS fails on segmented/enterprise
  Wi-Fi exactly when you need the fallback; manual entry is the floor.
- **QR-code pairing:** deferred — better UX than typing a code, same
  trust model; arrives with the box's physical display design.
- **Isar for the cache:** deferred — heavier native/codegen footprint for
  a cache of JSON maps; Hive satisfies the ENGINEERING.md mandate today.
- **App talks to engines directly:** rejected — the API boundary is what
  lets engines evolve behind one versioned protocol.
