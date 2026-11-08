# MLH GHW Builders Week — Tiger Data sample (Challenges 1, 3, 5)

**Event:** Global Hack Week: Builders Week, Nov 6–12, 2026  
**Status:** Preparation only — **not live-verified**. Do not push or run `run_live.sh` until direct user approval.

## Scope

Idempotent SQL under schema `builders_week`, capped sample data, Tiger CLI runbook, **mock** static/unittest checks. No Tiger Cloud provisioning from this agent without user approval.

## Review fixes (local, 2026-11-08)

- Nonempty hypertable conversion: `migrate_data => TRUE` on `device_events`
- Hypertable-safe uniqueness: `(recorded_at, fixture_key)`
- Fixture reload deletes only `fixture_batch = 'bw2026-demo-v1'` rows
- Join query orders lateral matches by **vector distance**
- `vectorscale`: no silent `WHEN OTHERS`; explicit WARNING if missing
- CLI runbook: free service requires `--region us-east-1 --cpu shared --memory shared` (or use existing service)
- **256-d** non-semantic lexical hashes (`data/README-embeddings.md`) — not AI semantic embeddings

## Embeddings

Default vectors are **256-dimensional lexical feature hashes** (no model API). Optional external CSV: `scripts/validate_embedding_csv.py`.

## Local mock tests

```bash
cd builders-week/tiger
python3 scripts/gen_deterministic_embeddings.py   # if you change ROWS
python3 -m unittest discover -s tests -p 'test_*.py' -v
./scripts/verify_local.sh
```

## Live Tiger Cloud (user approval required)

See [`cli/RUNBOOK.md`](cli/RUNBOOK.md). **No paid service creation** without verifying plan/billing.

## Layout

```
sql/00–05 + generated 04b_import_alert_embeddings.sql
data/   device_events_sample.csv, alert_embeddings_sample.csv, query_vectors.json
queries/ verification + similarity (generated vector literals)
cli/    RUNBOOK.md
tests/  static SQL invariants + embedding unit tests (MOCK)
```

Honest status: [`STATUS.md`](STATUS.md). Portable archive: [`docs/ARTIFACTS.md`](docs/ARTIFACTS.md).
