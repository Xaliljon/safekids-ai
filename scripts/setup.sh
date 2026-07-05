#!/usr/bin/env bash
# Guardian AI — one-shot development environment setup.
set -euo pipefail

cd "$(dirname "$0")/.."

echo "==> Checking toolchain"

if ! command -v uv >/dev/null 2>&1; then
  echo "==> Installing uv (https://docs.astral.sh/uv/)"
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
fi
echo "    uv $(uv --version | awk '{print $2}')"

if command -v flutter >/dev/null 2>&1; then
  echo "    flutter $(flutter --version 2>/dev/null | head -1 | awk '{print $2}')"
else
  echo "    WARNING: Flutter not found — mobile/dashboard/dart packages need it."
  echo "             https://docs.flutter.dev/get-started/install"
fi

if command -v docker >/dev/null 2>&1; then
  echo "    docker $(docker --version | awk '{print $3}' | tr -d ',')"
else
  echo "    WARNING: Docker not found — local stack (make stack-up) needs it."
fi

echo "==> Syncing Python workspace"
uv sync --all-packages

echo "==> Installing pre-commit hooks"
uv run pre-commit install

echo "==> Fetching Dart dependencies"
if command -v flutter >/dev/null 2>&1; then
  for dir in packages/dart/guardian_core packages/dart/guardian_api_client packages/dart/guardian_ui mobile dashboard; do
    (cd "$dir" && flutter pub get >/dev/null) && echo "    $dir OK"
  done
fi

echo ""
echo "Setup complete. Try: make lint && make test"
