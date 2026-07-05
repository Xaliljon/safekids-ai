# ai/

Guardian AI **model development** — the training side. Produces evaluated,
versioned, exported model artifacts. Runs on workstations/training servers,
never on the Edge Box.

## Layout

| Path | Responsibility |
|---|---|
| `guardian_ai/datasets/` | Dataset loaders and augmentation **code** (raw data lives in `/datasets` via DVC, never here). |
| `guardian_ai/training/` | Trainers for the V1 events: fall, zone-exit, cry. |
| `guardian_ai/evaluation/` | Benchmarks: accuracy, FP/FN rate, latency, robustness — the full ethics-mandated metric set (docs/04). |
| `guardian_ai/export/` | PyTorch → ONNX (→ TensorRT) export. Emits `model.onnx` + `manifest.json` conforming to `contracts/models`. |
| `configs/` | Training/evaluation configuration (no secrets). |

## Boundary rules

- The **only** thing `edge/` receives from here is a versioned artifact + manifest. No shared runtime code.
- Nothing here ships to production directly; models graduate through evaluation and the AI ethics checklist.
- Experiments start in `/research` and are promoted here via PR with evaluation results.
- Detector selection is blocked on **ADR-0003 (licensing)** — do not add an AGPL detector dependency.
