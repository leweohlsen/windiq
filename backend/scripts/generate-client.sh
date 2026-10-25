#!/usr/bin/env sh
# Regenerate the API client from the WindIQ OpenAPI spec.
# Usage: uv run scripts/generate-client.sh
set -euo pipefail

SPEC_URL="${WIQ_SPEC_URL:-https://windiq-mock-api.sliplane.app/openapi.json}"
OUT="packages/windiq_client"

cd "$(dirname "$0")/.."

uv run --no-sync openapi-python-client generate \
    --url "$SPEC_URL" \
    --output-path "$OUT" \
    --overwrite \
    --fail-on-warning

rm -rf "$OUT/.ruff_cache"

# openapi-python-client emits a Poetry-style pyproject, but uv needs PEP 621.
# See packages/windiq_client/pyproject.toml (committed, not regenerated).
echo "Done — if the spec added new schemes, review packages/windiq_client/pyproject.toml."
