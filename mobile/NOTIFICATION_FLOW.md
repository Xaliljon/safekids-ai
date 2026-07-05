# SafeKids Mobile — Notification Flows

- **Date:** 2026-07-05 (Sprint 13)
- **Reflects:** ADR-0014 (notifications), ADR-0015 (device API & mobile)

## Pairing flow

```
Guardian Box                              Phone
────────────                              ─────
displays 6-digit code    ──(human)──>     enters IP + code (PairingScreen)
                                          POST /api/v1/pair {code, device_name}
verifies code (single-use),
mints token, persists device  ──────>     {token, box_name, ws_port, cursor}
mints a NEW code                          stores PairedBox in Hive → trusted
```

No accounts, no cloud login. Trust is granted by a human who can read the
box's display, and persists on both sides across restarts.

## Realtime flow

```
fall → …engines… → NotificationEngine → LocalPushChannel
                                            ├── durable outbox (line N)
                                            └── DeviceApiServer broadcast
                                                     │ ws frame {kind: notification, payload}
                                              phone WS client
                                                     │ Hive persist → cursor = N
                                              NotificationRepository → UI updates
```

The notification center re-sorts newest-first; unread items show a
severity-colored dot until opened. Opening fetches incident details
(timeline of candidate events with explainable signals) from the box.

## Offline synchronization

The phone tracks a **cursor**: how many outbox lines it has seen. Each live
WS frame advances it by one; sync jumps it to the server's value.

```
Wi-Fi dies → WS stream ends → state = OFFLINE
  UI: amber banner, cached notifications remain fully usable
  ConnectionController: retry loop (cancellable delay, forever)

Wi-Fi returns → reconnect:
  1. GET /api/v1/notifications?after=<cursor>   ← everything missed
  2. merge into Hive + memory (dedup by notification id)
  3. cursor = server cursor
  4. reopen WS for live frames
Nothing is ever lost: the box's outbox is durable, the phone's cache is
durable, and the cursor stitches them together.
```

## Director actions

```
Confirm/Dismiss tap → POST /api/v1/incidents/<id>/resolve {decision, note}
box: RiskEngine.confirm/dismiss (reviewer = paired device name)
  → dismissals also start the false-positive suppression window
phone: applies the RETURNED status to every notification of that incident
       (the app never modifies incidents locally)
```

## Failure recovery

| Failure | Behavior |
|---|---|
| Wrong pairing code | 403; error shown; nothing stored |
| Box unreachable at launch | cached list + offline banner; retry forever |
| WS drops mid-stream | offline state → reconnect → cursor sync fills the gap |
| Sync request fails | stay offline, keep retrying; cache serves the UI |
| Resolve fails (box down) | error surfaced; incident stays pending; retry manually |
| Incident no longer open (404 on details) | cached notification fields shown; timeline marked unavailable |
| App killed | Hive restores notifications, read state, cursor, and the trusted box |
