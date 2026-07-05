# SafeKids Mobile — Architecture

- **Date:** 2026-07-05 (Sprint 13)
- **Reflects:** ADR-0015 (device API & mobile), CLAUDE.md Flutter mandates

## What this app is

The director's alert device: it receives SafetyIncident notifications from
the Guardian Edge Box **over the local network only** and records the
director's confirm/dismiss decisions. Fully offline-capable; no cloud, no
Firebase, no push services. The box is the single source of truth — the
app is a synchronized view with a decision button.

```
Flutter UI (presentation)
   │  Riverpod providers
Application (repository, connection controller — pure Dart + foundation)
   │  DeviceApi / NotificationCache interfaces
Infrastructure (DioDeviceApi + WebSocket, Hive cache)
   │
Guardian Device API (the box)          ← the app's only network peer
```

## Layers (Clean Architecture, CLAUDE.md stack)

| Layer | Contents | Rules |
|---|---|---|
| `src/presentation/` | PairingScreen, NotificationCenterScreen, IncidentDetailsScreen | no business logic in widgets; reads providers only |
| `src/application/` | `NotificationRepository` (state over the cache), `ConnectionController` (pair/reconnect/sync/resolve), `DeviceApi` + `NotificationCache` interfaces | no Flutter UI imports; no network/storage libraries |
| `src/infrastructure/` | `DioDeviceApi` (Dio + web_socket_channel), `HiveNotificationCache` | implements application interfaces; nothing above imports these directly |
| `guardian_core` (shared package) | `NotificationMessage`, `IncidentDetails`, `Severity`, `PairedBox` — strict wire parsing | pure Dart, reused by future dashboard |

State management: **Riverpod** (`providers.dart` is the composition root;
tests override `deviceApiProvider`/`notificationCacheProvider` with fakes).
Navigation: **GoRouter**, created once per app lifetime — rebuilds never
reset the stack. Storage: **Hive** (JSON maps, no codegen; ADR-0015).

## Invariants

- The app talks **only** to the Device API — never to risk/notification
  engines, never to a cloud.
- Incident status changes only from box responses (`applyResolution`);
  the app never invents state locally.
- Every notification is persisted to Hive before it is shown; Wi-Fi loss
  and app restarts lose nothing.
- Payloads are metadata-only; there are no images anywhere in this app.

## Testing (26 tests, 96.6% line coverage)

- Repository: cache restore, live/sync merge, dedup, read state, resolution fan-out.
- ConnectionController: pairing success/failure, restore-and-sync, live WS
  delivery, drop → offline → auto-reconnect → resync, retry-forever.
- Infrastructure: Hive round-trips across restarts; DioDeviceApi against a
  real in-test HTTP+WS server (auth headers, cursors, resolution, framing).
- Widgets: pairing flow, list ordering/unread/status chips, details +
  timeline, confirm/dismiss, offline banner with cached items.

See NOTIFICATION_FLOW.md for the runtime flows.
