#!/usr/bin/env bash
# Package a published Guardian dataset registry version into a zip for
# upload to Google Drive — read-only, the original registry is never
# touched. Default: Guardian Dataset v1 (guardian-fall-detection-v1@1.0.0).
#
#   GUARDIAN_DATASET_ROOT=/path/to/AI-Datasets ./scripts/package-dataset.sh \
#       [output-zip] [dataset-name] [version]
source "$(dirname "${BASH_SOURCE[0]}")/lib/common.sh"

need_cmd zip "Install zip (macOS: preinstalled; Linux: apt install zip)."

[ -n "${GUARDIAN_DATASET_ROOT:-}" ] || die \
    "GUARDIAN_DATASET_ROOT is not set. Point it at the directory containing your registry/ (see docs/COLAB_SETUP.md)."
[ -d "$GUARDIAN_DATASET_ROOT" ] || die "GUARDIAN_DATASET_ROOT does not exist: $GUARDIAN_DATASET_ROOT"

OUTPUT="${1:-$PWD/guardian-dataset-v1.zip}"
case "$OUTPUT" in
    /*) : ;;
    *) OUTPUT="$PWD/$OUTPUT" ;;
esac
NAME="${2:-guardian-fall-detection-v1}"
VERSION="${3:-1.0.0}"

RELATIVE="registry/$NAME/$VERSION"
DATASET_DIR="$GUARDIAN_DATASET_ROOT/$RELATIVE"
[ -d "$DATASET_DIR" ] || die "no such published dataset version: $DATASET_DIR"

rm -f "$OUTPUT"
say "packaging $NAME@$VERSION from $GUARDIAN_DATASET_ROOT"
# zip only reads the tree; nothing under GUARDIAN_DATASET_ROOT is modified.
( cd "$GUARDIAN_DATASET_ROOT" && zip -rq "$OUTPUT" "$RELATIVE" )

ok "wrote $OUTPUT ($(du -sh "$OUTPUT" | cut -f1))"
note "original dataset at $DATASET_DIR was not modified"
note "extracts to <root>/$RELATIVE — see docs/COLAB_SETUP.md for the expected layout"
