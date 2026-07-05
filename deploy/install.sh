#!/usr/bin/env bash
# Guardian Edge Box — one-command installer (ADR-0016).
#
#   curl -fsSL .../install.sh | bash        (or)   make install
#
# Idempotent: safe to re-run. Refuses to proceed when the environment
# validation fails; everything it decides is recorded in
# $GUARDIAN_HOME/reports/install-report.json.
set -euo pipefail

GUARDIAN_HOME="${GUARDIAN_HOME:-$HOME/guardian}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

say() { printf '\033[1;32m==>\033[0m %s\n' "$*"; }
die() { printf '\033[1;31mERROR:\033[0m %s\n' "$*" >&2; exit 1; }

say "Guardian Edge installer (home: $GUARDIAN_HOME)"

# 1. toolchain --------------------------------------------------------------
if ! command -v uv >/dev/null 2>&1; then
    say "installing uv (Python toolchain)"
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$PATH"
fi
command -v uv >/dev/null 2>&1 || die "uv is not on PATH after install; open a new shell and re-run"

# 2. runtime dependencies ---------------------------------------------------
say "syncing Python workspace"
uv sync --all-packages --quiet

# 3. environment validation (writes the install report) ---------------------
say "validating environment"
GUARDIAN_HOME="$GUARDIAN_HOME" uv run guardianctl check \
    || die "environment validation failed — see report above, fix and re-run"

# 4. detection model --------------------------------------------------------
if [ ! -d "$GUARDIAN_HOME/models/yolox-tiny" ]; then
    say "installing detection model (YOLOX-tiny, Apache-2.0)"
    uv run python -m guardian_edge.tools.install_yolox --dest "$GUARDIAN_HOME/models"
else
    say "detection model already installed"
fi

# 5. process-level auto-recovery (systemd, Linux only) -----------------------
if command -v systemctl >/dev/null 2>&1 && [ -d /etc/systemd/system ]; then
    say "installing systemd service (guardian-edge)"
    sed -e "s|@REPO@|$REPO_ROOT|g" \
        -e "s|@HOME@|$GUARDIAN_HOME|g" \
        -e "s|@USER@|$(id -un)|g" \
        deploy/guardian-edge.service | sudo tee /etc/systemd/system/guardian-edge.service >/dev/null
    sudo systemctl daemon-reload
    sudo systemctl enable guardian-edge
    say "service installed (start it with: sudo systemctl start guardian-edge)"
else
    say "systemd not found — skipping service install (run manually: uv run guardian-edge)"
fi

say "installation complete"
cat <<EOF

Next steps:
  1. Configure cameras:   GUARDIAN_HOME=$GUARDIAN_HOME uv run guardianctl wizard
  2. Run diagnostics:     GUARDIAN_HOME=$GUARDIAN_HOME uv run guardianctl diagnose
  3. Start the box:       sudo systemctl start guardian-edge   (or: uv run guardian-edge)
  4. Check health:        uv run guardianctl health

Full pilot instructions: PILOT_GUIDE.md
EOF
