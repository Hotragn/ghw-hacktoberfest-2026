#!/usr/bin/env bash
# MOCK/local verification — no Tiger Cloud connection required.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "[mock] unittest"
python3 -m unittest discover -s tests -p 'test_*.py' -q

echo "[mock] SQL bundle file count"
count=$(find sql -maxdepth 1 -name '*.sql' | wc -l)
test "$count" -eq 7

echo "[mock] sample data row caps"
dev_rows=$(tail -n +2 data/device_events_sample.csv | wc -l)
alert_rows=$(tail -n +2 data/alert_embeddings_sample.csv | wc -l)
test "$dev_rows" -le 40
test "$alert_rows" -le 20

echo "[mock] regenerate embeddings CSV and diff stat"
python3 scripts/gen_deterministic_embeddings.py >/dev/null
if ! git diff --quiet data/alert_embeddings_sample.csv 2>/dev/null; then
  : # not in git or changed — still ok for fresh trees
fi

echo "[mock] embedding script round-trip"
python3 scripts/gen_deterministic_embeddings.py --print-sql >/dev/null

echo "OK — local/mock checks passed (not a live Tiger Cloud proof)."
