# edge/

**Guardian Edge Box runtime** — the deploy side, and the heart of the platform.
Runs on NVIDIA Jetson (primary) and Intel N100 (secondary). Ingests cameras,
runs local inference, assesses risk, raises safety events. Fully functional
with **zero internet** (charter requirement); end-to-end alert latency budget
is **< 1 second**.

## Clean Architecture layout

| Layer | Path | Responsibility |
|---|---|---|
| Domain | `guardian_edge/domain/` | `SafetyEvent`, `Zone`, `Camera`, `RiskLevel` — pure Python, zero framework imports. |
| Application | `guardian_edge/application/` | Use cases: `DetectFall`, `DetectZoneExit`, `DetectCry`, `RaiseAlert`. |
| Infrastructure | `guardian_edge/infrastructure/camera/` | RTSP/ONVIF camera session management. |
| | `guardian_edge/infrastructure/inference/` | `EdgeInferencePipeline` — ONNX Runtime (canonical) and TensorRT (Jetson) backends behind one interface. |
| | `guardian_edge/infrastructure/audio/` | Cry-detection audio ingest (scope pending PRD). |
| | `guardian_edge/infrastructure/tracking/` | ByteTrack adapter. |
| | `guardian_edge/infrastructure/storage/` | Encrypted local event/clip store. |
| | `guardian_edge/infrastructure/sync/` | **Optional** metadata-only cloud sync. |
| Presentation | `guardian_edge/api/` | Local device API: health, config, provisioning. |

## Implementation status

| Subsystem | Status |
|---|---|
| **Camera service** (capture, discovery, health, recovery) | ✅ Implemented — see [architecture/camera-service.md](../architecture/camera-service.md) |
| Inference pipeline | Pending |
| Audio (cry detection) | Pending (scope blocked on PRD) |
| Storage / sync / device API | Pending |

Camera configuration: copy [`config/cameras.example.yaml`](config/cameras.example.yaml)
and register cameras explicitly; RTSP credentials come from environment
variables, never from the file. Entry point:
`guardian_edge.infrastructure.camera.wiring.create_camera_service()`.

## Boundary rules

- Dependencies point inward. Domain imports nothing above it.
- Loads models **only** via manifests conforming to `contracts/models` — models are replaceable without code changes.
- Talks to `backend/` only through `contracts/` schemas over the network. Never imports backend code.
- Raw video never leaves the device except human-approved short evidence clips.
- Python floor is 3.10 (JetPack 6 system Python) — see `pyproject.toml` before raising.
