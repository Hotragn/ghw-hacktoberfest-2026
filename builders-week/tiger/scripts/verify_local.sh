#!/usr/bin/env bash
# MOCK/local verification — no Tiger Cloud connection required.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "[mock] unittest"
python3 -m unittest discover -s tests -p 'test_*.py' -q

echo "[mock] committed CSV matches generator output"
BEFORE="$(mktemp)"
trap 'rm -f "$BEFORE"' EXIT
cp data/alert_embeddings_sample.csv "$BEFORE" 2>/dev/null || true
python3 scripts/gen_deterministic_embeddings.py
if [[ ! -f data/alert_embeddings_sample.csv ]] || ! cmp -s "$BEFORE" data/alert_embeddings_sample.csv; then
  echo "ERROR: committed CSV does not match gen_deterministic_embeddings.py output" >&2
  exit 1
fi

echo "[mock] SQL bundle file count"
count=$(find sql -maxdepth 1 -name '*.sql' | wc -l)
test "$count" -ge 8

echo "[mock] sample data row caps"
dev_rows=$(tail -n +2 data/device_events_sample.csv | wc -l)
alert_rows=$(tail -n +2 data/alert_embeddings_sample.csv | wc -l)
test "$dev_rows" -le 40
test "$alert_rows" -le 20

echo "[mock] validate embedding CSV"
python3 scripts/validate_embedding_csv.py data/alert_embeddings_sample.csv

echo "OK — local/mock checks passed (not live Tiger Cloud proof; no push implied)."
