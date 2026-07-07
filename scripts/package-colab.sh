#!/usr/bin/env bash
# Package this repo's SOURCE ONLY into guardian-ai.zip for upload to Google
# Drive / Google Colab. Datasets are never included — see
# scripts/package-dataset.sh and docs/COLAB_SETUP.md.
#
#   ./scripts/package-colab.sh [output-zip]
source "$(dirname "${BASH_SOURCE[0]}")/lib/common.sh"

need_cmd git "Install git."
need_cmd zip "Install zip (macOS: preinstalled; Linux: apt install zip)."

OUTPUT="${1:-$GUARDIAN_REPO/guardian-ai.zip}"
case "$OUTPUT" in
    /*) : ;;
    *) OUTPUT="$PWD/$OUTPUT" ;;
esac

cd "$GUARDIAN_REPO"
COMMIT="$(git rev-parse --short HEAD)"
STAGING="$(mktemp -d)"
trap 'rm -rf "$STAGING"' EXIT

say "archiving tracked source at $COMMIT"
git archive --format=tar HEAD | tar -x -C "$STAGING"

# Belt-and-suspenders on top of what git-archive already excludes via
# .gitignore (datasets/**, .venv, __pycache__): strip anything that
# shouldn't ship in a training-only package even if it were ever tracked.
rm -rf \
    "$STAGING/reports" \
    "$STAGING/ai/training/runs" \
    "$STAGING/datasets/registry" \
    "$STAGING/datasets/guardian_dataset_v1" \
    "$STAGING/ai/training/datasets/registry"
find "$STAGING" -type d \( -name __pycache__ -o -name .pytest_cache -o -name "*.egg-info" \) \
    -exec rm -rf {} + 2>/dev/null || true
find "$STAGING" -name .DS_Store -delete 2>/dev/null || true

rm -f "$OUTPUT"
( cd "$STAGING" && zip -rq "$OUTPUT" . )

ok "wrote $OUTPUT ($(du -sh "$OUTPUT" | cut -f1))"
note "source only — no .git, no datasets, no venv/caches, no reports, no runs"
note "pair with scripts/package-dataset.sh — see docs/COLAB_SETUP.md"
