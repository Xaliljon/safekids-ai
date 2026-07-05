# Guardian Edge — Release Notes

## 0.2.0 — Pilot Readiness (Sprint 14)

First release intended for deployment outside the lab: a kindergarten pilot
box that installs, monitors, diagnoses and recovers **without a developer**.

### Added
- **Production supervisor** (`guardian-edge`): one entrypoint wiring cameras →
  detection → tracking → events → risk → notifications → device API, with
  health, metrics, and watchdog attached.
- **`guardianctl` operator CLI**: environment check, camera setup wizard
  (ONVIF discovery + manual + connection/resolution/FPS test), diagnostics,
  live health, metrics export, configuration backup/restore.
- **One-command installer** (`deploy/install.sh`) with environment validation
  and machine-readable install report.
- **System health endpoint** (`:8790/health`, `:8790/metrics`): component
  status for camera/inference/tracking/risk/notifications plus CPU, RAM,
  disk, temperature, FPS, and network — machine-readable JSON.
- **Diagnostics** (`guardianctl diagnose`): exercises camera, AI, tracking,
  notification, and device-API subsystems against synthetic input; report
  includes versions, problems, and operator recommendations.
- **Structured logging**: JSON-lines per subsystem (system, vision, tracking,
  risk, notifications, device_api, installer) with size-based rotation.
- **Auto-recovery**: in-process service watchdog (restart + rate-limited
  warnings) layered under systemd process-level restart.
- **Backup & restore**: allowlisted configuration archive (cameras, trusted
  devices) — models, video, images, and logs excluded by construction.

### Unchanged (frozen architecture)
Camera Service, Vision Pipeline, Inference Runtime, Detector, Tracker,
Event Engine, Risk Engine, Notification Engine, Device API — no behavior
changes; the ops layer composes over their public APIs only.

### Known pilot limitations
- Single detection model (YOLOX-tiny, person class); fall detection is
  heuristic and every incident requires human verification (by design).
- Health endpoint is LAN-plaintext; the pilot network must be trusted
  (same threat model as the device API pairing, ADR-0015).
- 24-hour stability is verified by accelerated simulation plus lab soak,
  not yet by a multi-week field deployment — that is what the pilot is for.

## 0.1.0 — Foundation through Device Integration (Sprints 1–13)

Camera service (RTSP, discovery, recovery), vision pipeline, ONNX inference
runtime, model zoo, dataset platform, YOLOX-tiny integration, ByteTrack
multi-object tracking, event engine (fall candidates), risk engine
(human-verified incidents), local-first notification engine, LAN device API,
and the SafeKids Flutter app.
