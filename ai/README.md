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
| `guardian_ai/training/` | ✅ **Training platform** (Sprint 17): frozen YAML configs, experiment records ("no anonymous models"), registry-only data access, `DetectorFamily` port (engine never depends on one detector), resumable Trainer, compare + gated promotion — see [architecture/training-platform.md](../architecture/training-platform.md). No model trained yet — real training starts after architecture review. |
| `guardian_ai/evaluation/` | ✅ Pure-numpy detection metrics: P/R/F1, mAP@50, mAP@50-95, confusion matrix, absolute FP/FN — the full ethics-mandated metric set (docs/04). |
| `guardian_ai/export/` | ✅ PyTorch → ONNX (opset 17, batch=1) with structural + parity validation, automatic `manifest.json`, Guardian compatibility check against the model zoo contract. |
| `guardian_ai/train/` | ✅ CLI: `python -m guardian_ai.train` — train / resume / evaluate / export / benchmark / report / compare / promote. |
| `training/` | Workspace: `configs/`, `datasets/` (local registry), `scripts/make_dummy_dataset.py`, `notebooks/colab.ipynb`, `runs/` (experiments, gitignored), `models/` (local zoo). |

## Boundary rules

- The **only** thing `edge/` receives from here is a versioned artifact + manifest. No shared runtime code.
- Nothing here ships to production directly; models graduate through evaluation and the AI ethics checklist.
- Experiments start in `/research` and are promoted here via PR with evaluation results.
- Detector selection is blocked on **ADR-0003 (licensing)** — do not add an AGPL detector dependency.
