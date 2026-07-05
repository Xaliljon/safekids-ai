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
