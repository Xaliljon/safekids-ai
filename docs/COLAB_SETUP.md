# Guardian AI — Google Colab Training Setup

- **Date:** 2026-07-07
- **Audience:** anyone running the real training run on Colab
- **Reflects:** Sprint 20 workspace cleanup — datasets are external assets

## Why this exists

The repository must stay lightweight — it is not acceptable for git, Colab,
CI, or releases to carry the ~9GB Guardian Fall Detection Dataset. Datasets
are assets, not source code, and never enter the repository tree at all
(`datasets/` here holds documentation and registry structure only, never
raw videos, training images, labels, or exports).

Two things make this work everywhere — a laptop, a training server, or
Colab — without a single hardcoded path:

- **`GUARDIAN_DATASET_ROOT`** — an environment variable pointing at the
  directory that contains your `registry/`. Every dataset lookup resolves
  through it. If it is not set (and the config does not set
  `dataset.registry_root` explicitly), loading a training config fails
  loudly with instructions, never silently.
- **Two zips** — `guardian-ai.zip` (this repo's tracked source) and
  `guardian-dataset-v1.zip` (one published dataset version) are the only
  two things Colab needs, both built by scripts in `scripts/`.

## 1. Build the zips (on your machine, not Colab)

```bash
# Source only — no .git, no datasets, no venv/caches, no reports, no runs.
./scripts/package-colab.sh                # -> guardian-ai.zip

# The published dataset, read-only (never modifies the original).
export GUARDIAN_DATASET_ROOT=/Users/<you>/AI-Datasets   # wherever yours lives
./scripts/package-dataset.sh              # -> guardian-dataset-v1.zip
```

Both scripts accept an optional output path as their first argument if you
want the zip somewhere other than the current directory.
`package-dataset.sh` also accepts a dataset name and version
(`./scripts/package-dataset.sh out.zip guardian-fall-detection-v1 1.0.0` —
those are already the defaults).

## 2. Upload to Google Drive

Upload both zips once to `MyDrive/guardian-ai-colab/`:

```
MyDrive/
  guardian-ai-colab/
    guardian-ai.zip
    guardian-dataset-v1.zip
```

## 3. Run the notebook

Open `ai/training/notebooks/model-v1-training.ipynb` in Colab:

1. Runtime → Change runtime type → **T4 GPU**.
2. Runtime → **Run All**. No manual shell commands are needed.

The notebook, in order:

```
Mount Google Drive
        │
        ▼
Extract guardian-ai.zip     -> /content/guardian-ai
        │
        ▼
pip install -e ai
        │
        ▼
Extract guardian-dataset-v1.zip -> /content/guardian-ai-datasets (local disk,
        │                           not Drive — Drive reads are slow)
        ▼
Set GUARDIAN_DATASET_ROOT=/content/guardian-ai-datasets
        │
        ▼
Validate workspace (registry checksum re-verification — a bad
        │            extraction fails here, not mid-training)
        ▼
Train -> Evaluate -> Error Analysis -> Qualitative -> Export
        -> Benchmark -> COCO Comparison -> Candidate
        │
        ▼
Copy artifacts back to MyDrive/guardian-ai-models/model-v1/
```

If Colab disconnects mid-run, reconnect and re-run the mount/extract/install
cells (idempotent — extraction always overwrites), then
`guardian_ai.train resume --run <dir>` picks up from the last checkpoint.

## Expected directory layout

```
GUARDIAN_DATASET_ROOT/
  registry/
    guardian-fall-detection-v1/
      1.0.0/
        dataset.json
        checksums.json
        version.json
        taxonomy/
        annotations/
        videos/
        train/ val/ test/          # split membership
        training/                  # images/ + labels/ + data.yaml (Sprint 18 export)
```

This is exactly what `guardian-dataset-v1.zip` extracts, and exactly what
`VideoDatasetRegistry.get()` expects under `$GUARDIAN_DATASET_ROOT/registry`.

## Per-platform `GUARDIAN_DATASET_ROOT` examples

| Platform | Example |
|---|---|
| macOS | `/Users/<you>/AI-Datasets` |
| Linux | `/opt/guardian/datasets` |
| Colab | `/content/guardian-ai-datasets` (set automatically by the notebook) |

The project works unchanged on all three — nothing in source code assumes
any of these paths; they are just where different people happen to keep
`GUARDIAN_DATASET_ROOT` pointed.

## Local development

Nothing changes for local training/tests beyond setting the environment
variable once:

```bash
export GUARDIAN_DATASET_ROOT=/Users/<you>/AI-Datasets
uv run python -m guardian_ai.train train --config ai/training/configs/model-v1.yaml
```

The `smoke.yaml` / `training_fixtures.py`-based tests are unaffected — they
set `dataset.registry_root` explicitly (a tiny synthetic dataset, not a real
one), which always takes precedence over `GUARDIAN_DATASET_ROOT`.
