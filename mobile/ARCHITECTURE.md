# SafeKids Mobile — Architecture

- **Date:** 2026-07-06 (Sprint 15, Mobile UX 1.0; supersedes the Sprint 13 revision)
- **Reflects:** ADR-0015 (device API & mobile), ADR-0016 (box health surface), ENGINEERING.md Flutter mandates

## What this app is

The kindergarten director's window into the Guardian Edge Box **over the
local network only**: live safety alerts with human review, plus the box's
own health picture (cameras, subsystems, host metrics). Fully
offline-capable; no cloud, no Firebase, no push services. The box is the
single source of truth — the app is a synchronized view with a decision
button.

```
Flutter UI (presentation: 5-tab shell + wizard + incident review)
   │  Riverpod providers (providers.dart = composition root)
Application (repositories & controllers — pure Dart + foundation)
   │  DeviceApi / BoxStatusApi / NotificationCache interfaces
Infrastructure (DioDeviceApi + WebSocket, DioBoxStatusApi, Hive cache)
   │                                  │
Device API :8787/:8788 (auth'd)      Health surface :8790 (read-only)
        └────────── the Guardian Edge Box — the app's only peer ─────────┘
```

## Layers (Clean Architecture, ENGINEERING.md stack)

| Layer | Contents | Rules |
|---|---|---|
| `src/presentation/` | `shell` (bottom nav + live-alert gate), `dashboard`, `notification_center`, `incident_details`, `cameras`, `health`, `settings`, `pairing_wizard` + `qr_scan`, shared `widgets`/`format` | no business logic in widgets; reads providers only; every string via l10n |
| `src/application/` | `NotificationRepository` (+ `AlertFilter`: shelves/search/filters/pagination), `ConnectionController` (pair/unpair/reconnect/sync/resolve), `StatusController` (health poll + offline snapshot), `SettingsController` (`AppSettings`: theme/locale/alerting), interfaces | no Flutter UI imports; no network/storage libraries |
| `src/infrastructure/` | `DioDeviceApi` (Dio + web_socket_channel), `DioBoxStatusApi` (`:8790/health,/metrics`, capability-gated camera restart), `HiveNotificationCache` | implements application interfaces; nothing above imports these directly |
| `src/l10n/` | `app_en/ru/uz.arb` → generated `AppLocalizations` (uz/ru/en) | translations reviewed with the pilot kindergarten |
| `guardian_core` (shared package) | `NotificationMessage`, `IncidentDetails`, `Severity`, `PairedBox`, `BoxHealth`/`BoxMetrics`, `QrPairingPayload` | pure Dart, strict/tolerant wire parsing as documented per type |

State management: **Riverpod**. Navigation: **GoRouter** with a
`StatefulShellRoute` (Dashboard / Alerts / Cameras / Health / Settings),
created once per app lifetime; pairing state switches routes via
`refreshListenable` + redirect, never by recreating the router. Incident
details are `push`ed so back navigation works. Storage: **Hive** (JSON
maps, no codegen; ADR-0015).

## The two box surfaces

| Surface | Port | Auth | Used for |
|---|---|---|---|
| Device API | 8787 (HTTP) + 8788 (WS) | pairing token | notifications, incident details, confirm/dismiss |
| Health (ops layer, ADR-0016) | 8790 | none (read-only LAN monitoring) | dashboard, cameras, health screens |

They stay separate on purpose: alerts must keep working when the health
port is unreachable (older box, firewall), and vice versa. The
`StatusController` polls `/health` every 10 s while paired, keeps the last
snapshot in Hive, and every status screen renders that snapshot offline
with its age visible.

**Camera restart** is capability-gated: the app POSTs
`/api/v1/cameras/<id>/restart`; boxes up to v0.2 answer 404 and the UI
explains that on-box auto-recovery already restarts crashed cameras. No
frozen component was modified for this sprint — the box endpoint is a
documented follow-up.

## Alerting policy (device-local)

`AppSettings.shouldAlert` gates the in-app banner for live notifications:
master switch → sensitivity (minimum severity) → quiet hours. **CRITICAL
always alerts** — presentation settings never silence an emergency
(docs/04). Settings only shape presentation; box detection behavior is
never changed from the phone.

## Invariants

- The app talks **only** to the box — never to engines directly, never to a cloud.
- Incident status changes only from box responses (`applyResolution`);
  the app never invents state locally.
- Every notification, read/archive flag, setting and health snapshot is
  persisted to Hive before it is shown; Wi-Fi loss and restarts lose nothing.
- Payloads are metadata-only; there are no images anywhere in this app.
- Trust is local and revocable: forget-box clears the device side;
  box-side revocation is deleting the device from trusted_devices.json.

## Performance

- Lazy rendering everywhere (`ListView.builder`); alert history is
  paginated (50/page with load-more) so multi-month pilots stay smooth.
- Screens rebuild from `select`-scoped provider reads (e.g. the unread
  badge) rather than whole-repository watches where it matters.
- Offline cache serves every screen instantly at launch; the network only
  refreshes.

## Evidence (Sprint 16, ADR-0017)

Incident review embeds the evidence player: `EvidenceController` (one per
incident) asks the box for the record, fetches the thumbnail, downloads
clips with progress and keeps them in a size-bounded LRU `EvidenceCache`
for offline review. Two variants (original / AI analysis) cache
independently; playback is `video_player` behind an overridable builder
so widget tests stub the platform surface. No sharing paths exist. See
EVIDENCE_UX.md.

## Testing (108 tests: unit, repository, widget, golden, offline)

- Repository & filters: shelves (unread/read/archived) are disjoint;
  search across summary/camera/track; severity/camera filters; pagination;
  per-incident history; cache restore and resolution fan-out.
- Controllers: settings persistence + corrupt-data reset; quiet-hours
  (incl. overnight) and critical-override policy; status polling, failure
  degradation, snapshot restore, restart outcome mapping.
- guardian_core: BoxHealth/BoxMetrics wire parsing (merge, tolerance),
  QR payload parsing (strict rejection table).
- Widgets: pairing wizard (manual + failure), dashboard, notification
  center end-to-end (tabs/search/filters/archive/load-more), incident
  review incl. confirm dialog and offline fallback, cameras + unsupported
  restart, health screen, settings (theme/language/quiet hours), live
  alert gating.
- Goldens: dashboard, notification center, health, incident details at a
  fixed 390×844 viewport (`flutter test --update-goldens` to regenerate).
- Offline: warm cache → all network failing → every screen still renders
  with honest offline banners; local mutations still persist.
- Hive: round-trips across restarts for every stored kind.

See NOTIFICATION_FLOW.md for the runtime flows and UX_GUIDE.md for the
design language.
