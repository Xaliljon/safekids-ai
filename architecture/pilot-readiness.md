# Pilot Readiness (Operational Layer)

- **Date:** 2026-07-06 (Sprint 14)
- **Reflects:** ADR-0016 (operational readiness); composes over ADR-0006..0015
- **Scope:** install, run, monitor, diagnose, recover, backup — no engine changes

## Purpose

Everything between "the engines work in the lab" and "a kindergarten runs
this box unattended". The platform architecture is frozen; the operational
layer attaches from the outside, exclusively through public APIs.

```
                        ┌──────────────────────── guardian-edge (supervisor, main.py) ───────────────────────┐
                        │                                                                                     │
 cameras ──CameraService──> VisionPipeline (YOLOX + ByteTrack) ──> EventEngine ──> RiskEngine ──> Notification│
                        │        │  frozen engines, wired via their existing consumer seams        Engine     │
                        │        │                                                                    │       │
                        │        │                                                       LocalPushChannel ──> DeviceApiServer (:8787/:8788)
                        │        ▼                                                                            │
                        │   ops/ (ADR-0016, pure composition)                                                 │
                        │   ├─ SystemHealthCollector ─> HealthServer  :8790/health /metrics (JSON)            │
                        │   ├─ PerformanceMonitor     bounded 24h history, export to reports/                 │
                        │   ├─ ServiceWatchdog        is_healthy/restart per service, never gives up          │
                        │   └─ logging_setup          JSON-lines per subsystem, size-rotated                  │
                        └─────────────────────────────────────────────────────────────────────────────────────┘
                                     ▲                                            ▲
                          systemd (Restart=always)                      guardianctl (operator CLI)
                          process-level recovery                        check │ wizard │ diagnose │ health
                                                                        metrics │ backup │ restore
```

## The Guardian home (`$GUARDIAN_HOME`, default `~/guardian`)

| Path | Contents | In backup? |
|---|---|---|
| `config/cameras.yaml` | camera registrations | **yes** |
| `data/trusted_devices.json` | paired phones (ADR-0015) | **yes** |
| `data/outbox/` | durable notification log (ADR-0014) | no (device data) |
| `models/` | model zoo (ADR-0009) | no (reinstallable) |
| `logs/` | rotated JSON-lines logs | no (ephemeral) |
| `backups/`, `reports/` | archives, machine-readable reports | no |

Video and images are not listed because they never exist on disk —
the pipeline is metadata-only by construction (ADR-0014).

## Components (`edge/guardian_edge/ops/`)

| Module | Responsibility |
|---|---|
| `paths.py` | `GuardianHome` — the single filesystem layout |
| `logging_setup.py` | subsystem → rotated JSON-lines file routing |
| `monitoring.py` | host metrics (psutil), health collector, `:8790` HTTP server, performance monitor |
| `camera_probe.py` | wizard probe: connection, resolution, measured FPS — no AI |
| `install_check.py` | environment/dependency validation + install report |
| `watchdog.py` | supervised-service auto-recovery with crash-loop warnings |
| `backup.py` | allowlisted config backup/restore (zip + manifest) |
| `diagnostics.py` | exercises camera/AI/tracking/notifications/device-API with synthetic input; report with problems + recommendations |

Plus the two entrypoints: `main.py` (`guardian-edge`, the supervisor) and
`cli.py` (`guardianctl`, the operator command). Packaging lives in
`deploy/` (installer, systemd unit, release notes, rollback guide).

## Recovery model (layered, each layer simple)

| Failure | Detected by | Recovered by |
|---|---|---|
| camera disconnect / network loss | capture session read failure | Sprint-2 reconnect backoff (never gives up) |
| engine worker thread dies | watchdog `thread_alive` probe, 5s cadence | watchdog restart via public start/stop |
| crash loop (>3 restarts / 5 min) | watchdog rate window | keeps retrying **and** raises `/health` warning |
| whole process dies | systemd | `Restart=always`, 5s delay |
| box re-imaged | operator | `install.sh` + `guardianctl restore` |

## Testing

`test_ops_foundation` (home/logging/install-check/probe),
`test_ops_monitoring` (collector/HTTP/metrics), `test_ops_recovery`
(watchdog/backup, hostile-archive cases), `test_ops_diagnostics`,
`test_guardianctl` (CLI end-to-end, no prompts), and `test_ops_stability`
(`-m stress`): camera disconnect + network interruption against the real
camera service, 200-incident notification backlog, and a simulated 24-hour
watchdog soak (17,280 supervision cycles, injected failures, fake clock).
