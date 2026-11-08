#!/usr/bin/env bash
# Documented Tiger CLI examples — do not run blindly; set TIGER_SERVICE_NAME first.
# Source: https://www.tigerdata.com/docs/reference/tiger-cloud/tiger-cli
set -euo pipefail

: "${TIGER_SERVICE_NAME:?export TIGER_SERVICE_NAME first}"

echo "=== tiger service list ==="
tiger service list

echo "=== tiger db ping ==="
tiger db ping "$TIGER_SERVICE_NAME"

echo "=== tiger db extensions list ==="
tiger db extensions list "$TIGER_SERVICE_NAME"

echo "=== tiger db query (smoke) ==="
tiger db query "$TIGER_SERVICE_NAME" -c "SELECT version();"

echo "=== apply builders-week/tiger SQL via run_live.sh ==="
exec "$(dirname "$0")/../scripts/run_live.sh"
