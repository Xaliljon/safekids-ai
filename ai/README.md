# ai/

Guardian AI **model development** — the training side. Produces evaluated,
versioned, exported model artifacts. Runs on workstations/training servers,
never on the Edge Box.

## Layout

| Path | Responsibility |
|---|---|
| `guardian_ai/datasets/` | ✅ **Dataset platform** (Sprint 7): JSONL annotation format, versioned taxonomy, ethics-bearing manifests, deterministic splits, quality + privacy gates, metrics, immutable registry — see [architecture/dataset-platform.md](../architecture/dataset-platform.md), ADR-0010. Raw data lives in `/datasets` via DVC, never here. |
| `guardian_ai/acquisition/` | ✅ **Dataset acquisition & annotation** (Sprint 18): importers (UR Fall, Le2i, GMDCSA24, pilot evidence with full lineage), deterministic video normalization, Guardian Video Annotation v1, local web annotation tool, review workflow (imported→…→published, audited), quality + privacy gates, statistics PDF, immutable video dataset registry with training-ready export — see [architecture/dataset-acquisition.md](../architecture/dataset-acquisition.md). |
| `guardian_ai/dataset/` | ✅ CLI: `python -m guardian_ai.dataset` — import / import-pilot / annotate / validate / review / publish / report / statistics. |
| `guardian_ai/training/` | ✅ **Training platform** (Sprint 17) + **first real model** (Sprint 19) + **official-detector architecture** (Sprint 19.1): frozen YAML configs, experiment records ("no anonymous models"), registry-only data access (image *and* video/YOLO-export formats), `DetectorFamily` port (engine never depends on one detector — `tiny-ssd` smoke family; `yolox-nano/tiny/s/m/l` wrap the real, unmodified upstream Apache-2.0 YOLOX, never a Guardian-owned detector implementation), lazy memory-bounded video batching, mixed precision, checkpoint support (auto-download + checksum, custom checkpoints, backbone transfer), resumable Trainer, error analysis, qualitative export, COCO-pretrained comparison, compare + gated promotion — see [architecture/training-platform.md](../architecture/training-platform.md), [architecture/detector-integration.md](../architecture/detector-integration.md) and [reports/model-v1/](../reports/model-v1/). |
| `guardian_ai/training/detectors/yolox/` | ✅ The **only** place YOLOX-specific code may live (Sprint 19.1): variants, checkpoint download/loading, the Guardian↔upstream target-format adapter, and the calling-convention wrapper. Nothing outside this package imports `yolox.*`. |
| `guardian_ai/evaluation/` | ✅ Pure-numpy detection metrics: P/R/F1, mAP@50, mAP@50-95, confusion matrix, absolute FP/FN, plus error analysis (top FP/FN images, worst confidence, worst localization, most confused classes) — the full ethics-mandated metric set (docs/04). |
| `guardian_ai/export/` | ✅ PyTorch → ONNX (opset 17, batch=1) with structural + parity validation, automatic `manifest.json`, Guardian compatibility check against the model zoo contract. |
| `guardian_ai/train/` | ✅ CLI: `python -m guardian_ai.train` — train / resume / evaluate / export / benchmark / report / compare / promote / error-analysis / qualitative / coco-compare / candidate. |
| `training/` | Workspace: `configs/` (`smoke.yaml`, `training.yaml`, **`model-v1.yaml`** — the real Sprint 19 spec), `datasets/` (local registry), `scripts/make_dummy_dataset.py`, `notebooks/` (`colab.ipynb`, **`model-v1-training.ipynb`** — full T4 run), `runs/` (experiments, gitignored), `models/` (local zoo). |

## Boundary rules

- The **only** thing `edge/` receives from here is a versioned artifact + manifest. No shared runtime code.
- Nothing here ships to production directly; models graduate through evaluation and the AI ethics checklist.
- Experiments start in `/research` and are promoted here via PR with evaluation results.
- Detector selection is blocked on **ADR-0003 (licensing)** — do not add an AGPL detector dependency.
