# Edge Camera Service

- **Date:** 2026-07-05 (Sprint 2)
- **Reflects:** ADR-0001 (Clean Architecture per app, artifact/schema-only boundaries)
- **Scope:** camera capture only — no AI, no tracking, no persistence

## Purpose

The camera service turns a set of configured RTSP cameras into a reliable,
self-healing stream of in-memory frames plus a live health report. It is the
foundation the future AI pipeline consumes; it knows nothing about inference.

## Component view

```mermaid
flowchart LR
    subgraph domain [Domain]
        CAM[Camera]
        FR[Frame]
        CH[CameraHealth]
        DC[DiscoveredCamera]
    end
    subgraph application [Application]
        CS[CameraService]
        SES[CaptureSession xN]
        HM[HealthMonitor]
        P[[Ports: VideoStream / VideoStreamFactory / CameraDiscovery]]
    end
    subgraph infrastructure [Infrastructure]
        RTSP[OpenCvRtspStreamFactory FFmpeg]
        ONVIF[OnvifWsDiscovery]
        CFG[YAML config loader]
    end
    CONSUMER([FrameConsumer<br/>future AI pipeline])
    LISTENER([StatusListener<br/>future notification engine])

    CFG --> CS
    CS --> SES
    CS --> HM
    SES -- opens via --> P
    RTSP -. implements .-> P
    ONVIF -. implements .-> P
    SES --> CONSUMER
    HM --> LISTENER
    HM -- request_reconnect --> SES
```

Dependencies point inward: infrastructure implements application ports;
application uses domain only; the domain imports nothing.

## Camera state machine

```mermaid
stateDiagram-v2
    [*] --> IDLE
    IDLE --> CONNECTING: start()
    CONNECTING --> STREAMING: stream opened
    CONNECTING --> RECONNECTING: open failed
    STREAMING --> RECONNECTING: read failed / recovery requested
    RECONNECTING --> STREAMING: stream reopened
    RECONNECTING --> FAILED: >= failed_after_attempts consecutive failures
    FAILED --> STREAMING: camera returns (retries never stop)
    STREAMING --> STOPPED: stop()
    RECONNECTING --> STOPPED: stop()
    FAILED --> STOPPED: stop()
```

## Stream recovery

Two layers, both mandatory:

1. **In-session recovery.** Every read/connect failure closes the stream and
   reconnects with exponential backoff (`RetryPolicy`: 1s → 2s → 4s … capped
   at 30s). After 5 consecutive failures the camera reports **FAILED** so
   humans get alerted — but retrying continues forever at the capped delay: a
   camera must come back by itself when power or network returns.
2. **HealthMonitor stall detection.** A stream that stays "connected" but
   silently stops delivering frames is detected by frame age
   (> 10s ⇒ stall) and asked to reconnect. The hard-block case (a `read()`
   that never returns) is prevented one layer down by FFmpeg open/read
   timeouts (10s each) set in `OpenCvRtspStreamFactory` — a dead camera can
   never pin a capture thread.

## Health semantics

| Status | Meaning | Derivation |
|---|---|---|
| `HEALTHY` | streaming, recent frames | `STREAMING` and frame age ≤ 10s |
| `DEGRADED` | trying, or streaming but stale | `CONNECTING`/`RECONNECTING`, or `STREAMING` with frame age > 10s |
| `UNHEALTHY` | not producing and not connected | `IDLE`/`FAILED`/`STOPPED` |

`CameraHealth` also carries `frames_per_second` (10s window), totals, and
reconnect/failure counters. The `StatusListener` hook fires once per status
*transition* — that is where the notification engine will attach.

## Threading model

One daemon thread per camera (`camera-<id>`) plus one monitor thread.
Blocking reads are bounded by FFmpeg timeouts, so threads always regain
control to honor `stop()` and `request_reconnect()`. All public methods are
thread-safe. A crashing frame consumer loses that frame only; a crashing
health check never stops the monitor (docs/03: no single failure crashes the
platform).

## Discovery is assistive, never trusted

`OnvifWsDiscovery` sends a WS-Discovery multicast probe and parses replies
with **defusedxml** (untrusted network input). Results are *candidates* shown
to an operator; registration is always an explicit operator action with an
explicit RTSP URL. The box never auto-trusts devices found on the network
(docs/03 security by default; docs/04 human in control).

## Frame identity

Every captured `Frame` mints a `frame_id` (identity of the image — `sequence`
is only a per-stream counter that resets on reconnect) and a `correlation_id`
(trace token propagated through every downstream artifact derived from this
capture). Both are UUIDs generated in the `Frame` constructor, so no capture
path can forget them. See ADR-0007.

## Privacy properties

- Frames live in memory only; the camera service never persists video.
- RTSP credentials come from environment variables via `${VAR}` placeholders
  in `cameras.yaml`; they are never written to config files.
- Logs and error messages only ever contain `Camera.redacted_url`
  (`rtsp://***:***@host/…`); tests assert the redaction.

## Configuration

See `edge/config/cameras.example.yaml`. Loading is strict: unknown structure,
missing keys, duplicate ids, non-RTSP URLs, and unresolved `${ENV}`
placeholders all fail loudly at startup with `CameraConfigurationError`.

## Wiring

```python
from pathlib import Path
from guardian_edge.infrastructure.camera.wiring import create_camera_service

service = create_camera_service(Path("/etc/guardian/cameras.yaml"), frame_consumer=on_frame)
service.start()      # begins capture + health monitoring
...
service.stop()
```

## Out of scope (later sprints)

AI inference, object tracking, clip/evidence storage, the local device API
surface for health, and backend sync. The integration points for all of them
already exist: `FrameConsumer`, `StatusListener`, and `CameraService.health_report()`.
