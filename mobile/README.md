# mobile/

SafeKids mobile application (Flutter) for the kindergarten **director** — the
primary alert flow: receive notification → review event (clip, confidence,
classroom, timestamp) → confirm or dismiss. Human review is mandatory for every
AI alert (docs/04_AI_ETHICS.md).

## Status

✅ **Mobile UX 1.0 (Sprint 15):** five-tab production app — dashboard
(system status, cameras, CPU/RAM, last sync), notification center
(unread/read/archived, search, filters, date groups, pagination), incident
review (timeline, signals, evidence, track history), cameras (status, FPS,
counters, capability-gated restart), box health, pairing wizard (QR +
manual + trusted devices), settings (theme, uz/ru/en language, sensitivity,
quiet hours). Offline-first throughout. See
[ARCHITECTURE.md](ARCHITECTURE.md), [UX_GUIDE.md](UX_GUIDE.md),
[NOTIFICATION_FLOW.md](NOTIFICATION_FLOW.md); ADR-0015/0016. 86 tests
incl. goldens.

## Mandated stack (CLAUDE.md)

Riverpod (state + DI) · GoRouter (navigation) · Dio + web_socket_channel
(networking) · Hive (local storage; ADR-0015).

## Boundary rules

- Talks to the backend **only** through `packages/dart/guardian_api_client` (generated from `contracts/openapi`).
- Shared entities come from `packages/dart/guardian_core`; shared widgets/theme from `packages/dart/guardian_ui`.
- No business logic in widgets (docs/03, separation of concerns).
- This is an early-warning review tool, **not** a live-surveillance camera wall.
