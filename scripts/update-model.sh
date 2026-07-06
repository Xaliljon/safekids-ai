#!/usr/bin/env bash
# Install or replace the detection model through the Model Zoo pipeline
# (manifest + license gate + SHA256 verification + atomic install, ADR-0009).
#
#   ./scripts/update-model.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib/common.sh"

need_uv; need_workspace
mkdir -p "$GUARDIAN_HOME/models"

say "installing detection model into $GUARDIAN_HOME/models (Model Zoo pipeline)"
(cd "$GUARDIAN_REPO" && uv run python -m guardian_edge.tools.install_yolox \
    --dest "$GUARDIAN_HOME/models") || die "model install failed"

say "installed models"
for dir in "$GUARDIAN_HOME/models"/*/; do
    [ -d "$dir" ] || continue
    name="$(basename "$dir")"
    versions="$(ls "$dir" 2>/dev/null | tr '\n' ' ')"
    ok "$name  (versions: ${versions:-?})"
done

if edge_running; then
    warn "guardian-edge is running with the previous model — apply with: ./scripts/restart.sh"
fi
