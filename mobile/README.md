# mobile/

SafeKids mobile application (Flutter) for the kindergarten **director** — the
primary alert flow: receive notification → review event (clip, confidence,
classroom, timestamp) → confirm or dismiss. Human review is mandatory for every
AI alert (docs/04_AI_ETHICS.md).

## Status

✅ **Implemented (Sprint 13):** pairing, realtime notifications over the
LAN, offline-first cache, incident review with confirm/dismiss. See
[ARCHITECTURE.md](ARCHITECTURE.md) and [NOTIFICATION_FLOW.md](NOTIFICATION_FLOW.md);
ADR-0015. 26 tests, 96.6% coverage.

## Mandated stack (CLAUDE.md)

Riverpod (state + DI) · GoRouter (navigation) · Dio + web_socket_channel
(networking) · Hive (local storage; ADR-0015).

## Boundary rules

- Talks to the backend **only** through `packages/dart/guardian_api_client` (generated from `contracts/openapi`).
- Shared entities come from `packages/dart/guardian_core`; shared widgets/theme from `packages/dart/guardian_ui`.
- No business logic in widgets (docs/03, separation of concerns).
- This is an early-warning review tool, **not** a live-surveillance camera wall.
