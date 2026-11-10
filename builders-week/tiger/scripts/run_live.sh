#!/usr/bin/env bash
# LIVE Tiger Cloud driver — fails closed without TIGER_SERVICE_NAME. May write DDL/DML.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"

if [[ -z "${TIGER_SERVICE_NAME:-}" ]]; then
  echo "ERROR: set TIGER_SERVICE_NAME to your Tiger Cloud service name or id." >&2
  echo "Example: export TIGER_SERVICE_NAME='ghw-builders-week-tiger'" >&2
  exit 1
fi

if ! command -v tiger >/dev/null 2>&1; then
  echo "ERROR: tiger CLI not found. Install from https://www.tigerdata.com/docs/reference/tiger-cloud/tiger-cli" >&2
  exit 1
fi

echo "Pinging service: $TIGER_SERVICE_NAME"
tiger db ping "$TIGER_SERVICE_NAME"

SQL_FILES=(
  sql/00_schema.sql
  sql/01_extensions.sql
  sql/02_table_plain.sql
  sql/02_import_device_events.sql
  sql/03_convert_hypertable.sql
  sql/04_hybrid_vector.sql
  sql/04b_import_alert_embeddings.sql
  sql/05_indexes.sql
)

if [[ ! -f "$ROOT/sql/04b_import_alert_embeddings.sql" ]]; then
  echo "ERROR: missing sql/04b_import_alert_embeddings.sql — run: python3 scripts/embed_semantic.py" >&2
  exit 1
fi

for rel in "${SQL_FILES[@]}"; do
  f="$ROOT/$rel"
  echo "==> tiger db query -f $rel"
  tiger db query "$TIGER_SERVICE_NAME" -f "$f"
done

echo "==> verification (read-only)"
for q in queries/verify_extensions.sql queries/verify_hypertable_chunks.sql; do
  tiger db query "$TIGER_SERVICE_NAME" --read-only -f "$ROOT/$q"
done

echo "Live apply complete. Run remaining queries under queries/ manually or via cli/RUNBOOK.md"
