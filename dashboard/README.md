# dashboard/

Guardian AI web dashboard (**Flutter Web** — see ADR-0001 §8) for owners and
administrators: multi-branch overview, device & camera health, event history,
alert statistics, reports.

## Status

Placeholder. `pubspec.yaml` pins the stack; the app scaffold lands after
foundation review.

## Boundary rules

- Talks to the backend **only** through `packages/dart/guardian_api_client`.
- Shares `guardian_core` (entities) and `guardian_ui` (design system) with the mobile app — that sharing is why Flutter Web was chosen.
- Displays events and health, **never** a live-camera surveillance wall (product philosophy, docs/02).
- No business logic in widgets.
