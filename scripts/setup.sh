#!/usr/bin/env bash
# Guardian AI — environment setup: verify prerequisites, install
# dependencies, create GUARDIAN_HOME, fetch the demo model.
#
#   ./scripts/setup.sh            # full setup (also used by `make setup`)
#   GUARDIAN_HOME=/data/guardian ./scripts/setup.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib/common.sh"

cd "$GUARDIAN_REPO"
FAILED=0

say "Guardian AI setup (repo: $GUARDIAN_REPO)"

# ------------------------------------------------------- verify toolchain ----
say "verifying prerequisites"

if command -v python3 >/dev/null 2>&1; then
    PY_VERSION="$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
    if python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)'; then
        ok "python $PY_VERSION (minimum 3.10)"
    else
        err "python $PY_VERSION is too old — Guardian needs 3.10+"; FAILED=1
    fi
else
    err "python3 not found — install Python 3.10+"; FAILED=1
fi

if command -v uv >/dev/null 2>&1; then
    ok "uv $(uv --version | awk '{print $2}')"
else
    say "installing uv (https://docs.astral.sh/uv/)"
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$PATH"
    command -v uv >/dev/null 2>&1 && ok "uv installed" || { err "uv install failed"; FAILED=1; }
fi

if command -v git >/dev/null 2>&1; then
    ok "git $(git --version | awk '{print $3}')"
else
    err "git not found — install git"; FAILED=1
fi

if command -v ffmpeg >/dev/null 2>&1; then
    ok "ffmpeg $(ffmpeg -version 2>/dev/null | head -1 | awk '{print $3}')"
else
    err "ffmpeg not found — brew install ffmpeg (macOS) / apt install ffmpeg (Linux)"; FAILED=1
fi

if command -v docker >/dev/null 2>&1; then
    if docker info >/dev/null 2>&1; then
        ok "docker $(docker --version | awk '{print $3}' | tr -d ',') (running)"
    else
        warn "docker installed but not running — needed for the live demo (demo-menu.sh)"
    fi
else
    warn "docker not found — the live demo RTSP rig needs it"
fi

if command -v flutter >/dev/null 2>&1; then
    ok "flutter $(flutter --version 2>/dev/null | head -1 | awk '{print $2}')"
else
    warn "flutter not found — only needed for the mobile app"
fi

[ "$FAILED" -eq 0 ] || die "fix the failed prerequisites above and re-run ./scripts/setup.sh"

# --------------------------------------------------- install dependencies ----
say "syncing Python workspace"
uv sync --all-packages --quiet
ok "workspace synced"

if uv run python -c "import cv2" 2>/dev/null; then
    ok "opencv $(uv run python -c 'import cv2; print(cv2.__version__)')"
else
    die "OpenCV failed to import after sync — see the uv output above"
fi

say "installing pre-commit hooks"
if [ -d .git ]; then
    uv run pre-commit install >/dev/null && ok "hooks installed"
else
    warn "not a git checkout — skipping hooks"
fi

if command -v flutter >/dev/null 2>&1; then
    say "fetching Dart dependencies"
    for dir in packages/dart/guardian_core packages/dart/guardian_api_client packages/dart/guardian_ui mobile dashboard; do
        (cd "$dir" && flutter pub get >/dev/null 2>&1) && ok "$dir" || warn "$dir (pub get failed)"
    done
fi

# ---------------------------------------------------------- guardian home ----
say "creating Guardian home ($GUARDIAN_HOME)"
GUARDIAN_HOME="$GUARDIAN_HOME" guardianctl check \
    || die "environment validation failed — see the report above"
mkdir -p "$RUN_DIR"
ok "layout ready (config/ models/ data/ logs/ backups/ reports/ run/)"

# ------------------------------------------------------------ demo model ----
if model_installed; then
    ok "detection model already installed (yolox-tiny)"
else
    say "downloading detection model (YOLOX-tiny, Apache-2.0)"
    (cd "$GUARDIAN_REPO" && uv run python -m guardian_edge.tools.install_yolox \
        --dest "$GUARDIAN_HOME/models") || die "model install failed"
    ok "model installed"
fi

# ---------------------------------------------------------------- summary ----
echo
say "setup complete"
cat <<EOF
    Guardian home:  $GUARDIAN_HOME
    Model:          $GUARDIAN_HOME/models/yolox-tiny
    Install report: $GUARDIAN_HOME/reports/install-report.json

    Next steps:
      ./scripts/demo-menu.sh # pick a demo (live AI / incidents / your video)
      make lint && make test # development gates
EOF
