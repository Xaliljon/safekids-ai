#!/usr/bin/env bash
# Guardian AI — regenerate code from contracts/ (single source of truth).
#
# Planned generation targets (activated as contracts land):
#   contracts/openapi/v1  -> packages/dart/guardian_api_client (Dart client)
#   contracts/events      -> packages/python/guardian_common (pydantic models)
#   contracts/models      -> model manifest validators (ai/export, edge inference)
#
# CI will fail if committed generated code is stale relative to contracts/.
set -euo pipefail

cd "$(dirname "$0")/.."

if ! find contracts -type f \( -name '*.yaml' -o -name '*.yml' -o -name '*.json' \) | grep -q .; then
  echo "codegen: no contracts defined yet — nothing to generate."
  exit 0
fi

echo "codegen: contracts found but generators are not wired yet."
echo "         Wire generators in this script before merging contract changes."
exit 1
