# Tiger CLI runbook — MLH Builders Week Challenge 3

Official references:

- [Tiger CLI reference](https://www.tigerdata.com/docs/reference/tiger-cloud/tiger-cli)
- [Tiger CLI and MCP overview](https://www.tigerdata.com/docs/learn/tiger-cli-mcp)
- [Common tasks](https://www.tigerdata.com/docs/build/tiger-cli-mcp/common-tasks)

This runbook uses **Tiger CLI only** (not MCP). Commands below match the public CLI reference as of late 2025/2026 (`tiger db query`, `tiger db psql`, `tiger db extensions list`).

## Prerequisites

1. Install Tiger CLI per [reference install section](https://www.tigerdata.com/docs/reference/tiger-cloud/tiger-cli).
2. Authenticate (browser or headless device code):

```bash
tiger auth login
# Remote / SSH-only machine:
tiger auth login --headless
```

3. Create a **free** Tiger Cloud service via [quickstart](https://www.tigerdata.com/docs/get-started) or:

```bash
tiger service list
tiger service create --name ghw-builders-week-tiger
```

4. Export the service name (never commit passwords):

```bash
export TIGER_SERVICE_NAME='ghw-builders-week-tiger'
```

## Connectivity checks

```bash
tiger db ping "$TIGER_SERVICE_NAME"
tiger db uri "$TIGER_SERVICE_NAME"
tiger db extensions list "$TIGER_SERVICE_NAME"
```

Expected extensions for this sample: `timescaledb`, `vector`; on Tiger Cloud you should also see `vectorscale`.

## Apply SQL bundle (Challenges 1 + 5)

From repository root:

```bash
cd builders-week/tiger
./scripts/run_live.sh
```

Or run files individually:

```bash
ROOT="$(pwd)"
for f in sql/00_schema.sql sql/01_extensions.sql sql/02_table_plain.sql \
         sql/02_import_device_events.sql sql/03_convert_hypertable.sql \
         sql/04_hybrid_vector.sql sql/05_indexes.sql; do
  echo "==> $f"
  tiger db query "$TIGER_SERVICE_NAME" -f "$ROOT/$f"
done
```

## Verification queries (read-only safe)

```bash
tiger db query "$TIGER_SERVICE_NAME" --read-only -f queries/verify_extensions.sql
tiger db query "$TIGER_SERVICE_NAME" --read-only -f queries/verify_hypertable_chunks.sql
tiger db query "$TIGER_SERVICE_NAME" --read-only -f queries/similarity_filtered_time.sql
tiger db query "$TIGER_SERVICE_NAME" --read-only -f queries/similarity_filtered_metadata.sql
tiger db query "$TIGER_SERVICE_NAME" --read-only -f queries/similarity_l2.sql
```

## Interactive inspection (optional)

```bash
tiger db psql "$TIGER_SERVICE_NAME"
```

Inside `psql`:

```sql
SET search_path TO builders_week, public;
\d+ device_events
SELECT * FROM timescaledb_information.hypertables WHERE hypertable_schema = 'builders_week';
```

## Agent integration note (Challenge 3)

Point your agent tooling at the same commands: `tiger db query` accepts `-f` for SQL files and `--output json` for machine-readable results ([CLI reference](https://www.tigerdata.com/docs/reference/tiger-cloud/tiger-cli)). Store only the service **name** in repo config; fetch URIs with `tiger db uri` at runtime.

## What to capture for MLH evidence

- Redacted output of `verify_hypertable_chunks.sql` (hypertable + chunk rows).
- Redacted output of one similarity query showing distance column.
- Screenshot of `tiger service list` or Console service page (no password).
