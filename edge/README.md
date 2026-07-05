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
| | `guardian_edge/infrastructure/inference/` | Model runtime backends — ONNX Runtime (canonical) and TensorRT (Jetson) behind the `InferenceEngine` port. |
| | `guardian_edge/infrastructure/vision/` | Task-level detectors (`DummyDetector` today) and the OpenCV overlay renderer. |
| | `guardian_edge/infrastructure/audio/` | Cry-detection audio ingest (scope pending PRD). |
| | `guardian_edge/infrastructure/tracking/` | ByteTrack adapter. |
| | `guardian_edge/infrastructure/storage/` | Encrypted local event/clip store. |
| | `guardian_edge/infrastructure/sync/` | **Optional** metadata-only cloud sync. |
| Presentation | `guardian_edge/api/` | Local device API: health, config, provisioning. |

## Implementation status

| Subsystem | Status |
|---|---|
| **Camera service** (capture, discovery, health, recovery) | ✅ Implemented — see [architecture/camera-service.md](../architecture/camera-service.md) |
| **Vision pipeline** (Detector port, DummyDetector, overlay) | ✅ Foundation — see [architecture/vision-pipeline.md](../architecture/vision-pipeline.md), ADR-0006 |
| **Inference runtime** (ONNX Runtime engine, loader, registry, validation, metrics) | ✅ Implemented — see [architecture/inference-runtime.md](../architecture/inference-runtime.md), ADR-0008 |
| **Detector abstraction** (EngineDetector, thresholds, NMS, mapper, dummy ONNX detector) | ✅ Implemented — model families plug in as a Preprocessor + OutputDecoder pair |
| **Model management** (zoo: atomic installs, license gate, rollback, OTA layout) | ✅ Implemented — see [architecture/model-management.md](../architecture/model-management.md), ADR-0009 |
| **Real detection model** (YOLOX-tiny, Apache-2.0; live RTSP demo, benchmarks) | ✅ Integrated — `make model-yolox && make demo-vision`; ADR-0003 |
| **Multi-object tracking** (in-house ByteTrack, persistent ids, lifecycle) | ✅ Implemented — optional pipeline stage; ADR-0011 |
| **Event engine** (track history → explainable PotentialFall candidates) | ✅ Foundation — see [architecture/event-engine.md](../architecture/event-engine.md), ADR-0012 |
| **Risk engine** (candidates → PENDING_REVIEW SafetyIncidents; human review API) | ✅ Implemented — see [architecture/risk-engine.md](../architecture/risk-engine.md), ADR-0013 |
| **Notification engine** (incidents → local-first delivered notifications) | ✅ Implemented — see [architecture/notification-engine.md](../architecture/notification-engine.md), ADR-0014 |
| TensorRT engine (Jetson) | Pending (bench hardware job) |
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
