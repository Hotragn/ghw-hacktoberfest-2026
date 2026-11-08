# Tiger CLI runbook — MLH Builders Week Challenge 3

**Do not run** until you approve Tiger Cloud access. Shared CLI flags are **not** a guarantee of zero total account cost — verify storage, plan limits, and billing in [Tiger Console](https://console.cloud.tigerdata.com/) before any `service create`.

Official CLI reference: https://www.tigerdata.com/docs/reference/tiger-cloud/tiger-cli

## Authentication (user only)

```bash
tiger auth login
# or: tiger auth login --headless
```

## Prefer an existing service

```bash
tiger service list
export TIGER_SERVICE_NAME='your-service'
```

## Optional new service — blocked without billing review

Only after **you** confirm the account/plan allows free shared compute and you accept any storage/egress charges:

```bash
tiger service create --name ghw-builders-week-tiger \
  --region us-east-1 --cpu shared --memory shared
```

If plan eligibility is unclear, **do not create** — use an existing service or stop.

## Connectivity

```bash
tiger db ping "$TIGER_SERVICE_NAME"
tiger db extensions list "$TIGER_SERVICE_NAME"
```

## Apply SQL (separate sessions per file; not one transaction)

```bash
cd builders-week/tiger
python3 scripts/gen_deterministic_embeddings.py   # refresh 04b if ROWS changed
./scripts/run_live.sh
```

## Verification queries (read-only)

```bash
tiger db query "$TIGER_SERVICE_NAME" --read-only -f queries/verify_extensions.sql
tiger db query "$TIGER_SERVICE_NAME" --read-only -f queries/verify_hypertable_chunks.sql
tiger db query "$TIGER_SERVICE_NAME" --read-only -f queries/verify_vector_index.sql
```

Rerun `02_import_device_events.sql` and `04b_import_alert_embeddings.sql` should **not** delete unrelated rows (ON CONFLICT DO NOTHING only).
