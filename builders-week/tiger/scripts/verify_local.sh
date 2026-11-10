#!/usr/bin/env bash
# MOCK/local verification — no Tiger Cloud connection required.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "[mock] unittest"
python3 -m unittest discover -s tests -p 'test_*.py' -q

if python3 -c "import sentence_transformers" 2>/dev/null; then
  echo "[mock] regenerate semantic embeddings and compare CSV"
  BEFORE="$(mktemp)"
  trap 'rm -f "$BEFORE"' EXIT
  cp data/alert_embeddings_sample.csv "$BEFORE" 2>/dev/null || true
  python3 scripts/embed_semantic.py
  if [[ ! -f data/alert_embeddings_sample.csv ]] || ! cmp -s "$BEFORE" data/alert_embeddings_sample.csv; then
    echo "ERROR: committed CSV does not match embed_semantic.py output" >&2
    exit 1
  fi
else
  echo "[skip] sentence_transformers not installed — skip CSV regen check"
fi

echo "[mock] SQL bundle file count"
count=$(find sql -maxdepth 1 -name '*.sql' | wc -l)
test "$count" -ge 8

echo "[mock] validate embedding CSV"
python3 scripts/validate_embedding_csv.py data/alert_embeddings_sample.csv

echo "OK — local/mock checks (not live DB proof)."
