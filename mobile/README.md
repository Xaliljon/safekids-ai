# mobile/

SafeKids mobile application (Flutter) for the kindergarten **director** — the
primary alert flow: receive notification → review event (clip, confidence,
classroom, timestamp) → confirm or dismiss. Human review is mandatory for every
AI alert (docs/04_AI_ETHICS.md).

## Status

Placeholder. `pubspec.yaml` pins the stack; the app scaffold (flavors,
composition root, Clean Architecture feature layout) lands after foundation review.

## Mandated stack (CLAUDE.md)

Riverpod (state + DI) · GoRouter (navigation) · Dio via `guardian_api_client`
(networking) · Isar (local storage).

## Boundary rules

- Talks to the backend **only** through `packages/dart/guardian_api_client` (generated from `contracts/openapi`).
- Shared entities come from `packages/dart/guardian_core`; shared widgets/theme from `packages/dart/guardian_ui`.
- No business logic in widgets (docs/03, separation of concerns).
- This is an early-warning review tool, **not** a live-surveillance camera wall.
