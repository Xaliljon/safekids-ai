# datasets/

DVC pointer files **only**. Raw data — video, audio, annotations — lives in
private, access-controlled storage and never enters git.

## Why this is strict

This project's data involves **children**. Mishandling it is an existential
legal, ethical, and trust risk (docs/04_AI_ETHICS.md, dataset ethics).
Enforcement is layered: `.gitignore` excludes everything but pointers, the
pre-commit hook blocks files > 1 MiB, and CI re-checks on every push.

## Rules (from docs/04)

- Lawfully collected, with documented consent.
- Bias evaluated and documented per dataset version.
- Anonymized and minimized where possible; deleted when no longer needed.
- Access is need-to-know; annotation workforce access is logged.

## Workflow (once DVC is initialized)

1. `dvc add datasets/<name>` — creates the `.dvc` pointer, git-tracks only that.
2. `dvc push` — uploads to the private remote.
3. Dataset **loaders** are code and live in `ai/guardian_ai/datasets/`, not here.

## Where the actual data lives today (pre-DVC)

DVC isn't initialized yet, so published dataset registries live outside
the repo entirely, pointed at through the `GUARDIAN_DATASET_ROOT`
environment variable — never a hardcoded path. This directory (`datasets/`)
never holds registry/workspace bytes, only this documentation. See
[`docs/COLAB_SETUP.md`](../docs/COLAB_SETUP.md) for how to point
`GUARDIAN_DATASET_ROOT` at your copy (local dev, a training server, or a
Colab session) and how to package a dataset version for upload.
