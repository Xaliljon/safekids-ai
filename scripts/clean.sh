#!/usr/bin/env bash
# Remove temporary files, caches and build artifacts.
# Keeps: models, configuration, data, backups, current logs.
#
#   ./scripts/clean.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib/common.sh"

say "cleaning repository caches and build artifacts"
cd "$GUARDIAN_REPO"
rm -rf .pytest_cache .ruff_cache .mypy_cache htmlcov .coverage dist
find . -type d -name __pycache__ -not -path "./.git/*" -not -path "./.venv/*" \
    -exec rm -rf {} + 2>/dev/null || true
rm -rf mobile/build mobile/coverage mobile/test/failures
ok "repo caches removed (.venv kept — remove manually if needed)"

if [ -d "$GUARDIAN_HOME" ]; then
    say "cleaning Guardian home temporaries ($GUARDIAN_HOME)"
    # Rotated log generations are temp; the current .log files stay.
    find "$LOGS_DIR" -name "*.log.[0-9]*" -delete 2>/dev/null || true
    # Stale pid files from dead processes.
    for pid_file in "$RUN_DIR"/*.pid; do
        [ -f "$pid_file" ] || continue
        kill -0 "$(cat "$pid_file")" 2>/dev/null || rm -f "$pid_file"
    done
    ok "rotated logs and stale pid files removed"
    note "kept: models/ config/ data/ backups/ reports/ and current logs"
else
    note "no Guardian home at $GUARDIAN_HOME — nothing to clean there"
fi

say "clean complete"
