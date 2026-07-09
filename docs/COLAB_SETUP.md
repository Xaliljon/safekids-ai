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

Upload both zips once directly to the root of `MyDrive`:

```
MyDrive/
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
        │  (aborts with a clear error if the zip is missing or extraction
        │   didn't produce ai/pyproject.toml)
        ▼
pip install uv, then uv sync --project ai   (NOT plain `pip install -e ai`
        │                                     — see "Why uv, not pip" below)
        ▼
Extract guardian-dataset-v1.zip -> /content/datasets (local disk,
        │                           not Drive — Drive reads are slow)
        ▼
Set GUARDIAN_DATASET_ROOT=/content/datasets   (automatic — no manual
        │                                       %env/export step)
        ▼
Validate workspace: /content/datasets/registry must exist, then every
        │            file's checksum is re-verified — a missing or
        │            corrupt extraction aborts here, not mid-training
        ▼
Train (run dir on Drive, --auto-resume) -> Evaluate -> Error Analysis
        -> Qualitative -> Export -> Benchmark -> COCO Comparison -> Candidate
        │
        ▼
Copy artifacts back to MyDrive/guardian-ai-models/model-v1/
```

Every one of these steps raises a `RuntimeError` with an exact, actionable
message on failure — under Colab's Run All, an uncaught exception stops
execution at that cell rather than limping forward with a half-built
workspace and failing confusingly three cells later.

## Resuming after a disconnect (Sprint 20.1)

Colab routinely drops the runtime before a 30-epoch run finishes. The
notebook is built so recovery is simply **Run All again — no manual
resume command, no lost work.**

Two things make that safe:

- The train cell passes **`--output-dir {DRIVE_OUT}/runs`**, so the run
  directory lives on Google Drive, not on ephemeral `/content`. Every
  epoch atomically flushes (temp file + rename, so a mid-write disconnect
  never truncates anything):
  - `checkpoints/last.pt` — model, optimizer, scheduler, **AMP scaler**,
    **RNG state** (python/numpy/torch/cuda) and the epoch number,
  - `checkpoints/best.pt` — whenever the tracked metric improves,
  - `history.json`, `metrics.json`, `experiment.json`, `training.log`.
- The train cell passes **`--auto-resume`**, which finds the newest
  unfinished run for this config under the output dir and continues it
  from `epoch + 1`, restoring optimizer, scheduler, AMP scaler, RNG state
  and the early-stopping counters. A run that already reached the end is
  detected and left untouched; if no run exists yet, a fresh one starts.

So the recovery procedure is: reconnect → **Runtime → Run All**. The
mount/extract/install/dataset cells are idempotent, and training picks up
where it left off. (The lower-level `guardian_ai.train resume --run <dir>`
command still exists for manual use, but the notebook never needs it.)

## Why `uv`, not `pip install -e ai`

`guardian_ai` depends on the real, unmodified upstream YOLOX (Sprint
19.1's `DetectorFamily` wrapper around it, never a vendored copy — see
[architecture/training-platform.md](../architecture/training-platform.md)
and [architecture/detector-integration.md](../architecture/detector-integration.md)).
That dependency is pinned to an exact git commit and needs two
`[tool.uv]`-only settings to install correctly:

- `no-build-isolation-package = ["yolox"]` — its `setup.py` needs `torch`
  importable at build time (to optionally precompile a C++ op); plain
  pip's per-package build isolation hides it, and pip has no per-package
  override for this (only an all-or-nothing `--no-build-isolation`, which
  also breaks unrelated packages' own build backends).
- `override-dependencies` — its `requirements.txt` pins ancient exact
  `onnx`/`onnxruntime` versions that conflict with the modern versions
  our own export/eval pipeline needs; pip has no equivalent override
  mechanism.

Plain `pip install -e ai` reliably fails with
`AssertionError: torch is required for pre-compiling ops, please install
it first` — reproduced and confirmed in a clean venv. `uv sync --project
ai` is the same install path local development and CI already use, not a
Colab-specific workaround, and it produces a `.venv` at the workspace
root (not inside `ai/`) that the notebook prepends to `PATH` so every
later `!python`/`!pip` cell transparently uses it.

The install cell also sets `MPLBACKEND=Agg`. Colab exports `MPLBACKEND`
pointing at its own IPython-inline matplotlib backend, which exists only
in Colab's system Python, not our venv. `guardian_ai` imports matplotlib
(report rendering) and matplotlib validates `MPLBACKEND` at import time,
so without this every venv subprocess (workspace validation, `train`,
`report`, …) crashes with `ValueError: Key backend:
'module://matplotlib_inline.backend_inline' is not a valid value`. `Agg`
is the headless backend those reports render with anyway; the notebook
only ever displays charts via `IPython.display.Image` on saved PNGs,
never in-kernel matplotlib, so forcing it is safe.

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
| Colab | `/content/datasets` (set automatically by the notebook, zero manual steps) |

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
