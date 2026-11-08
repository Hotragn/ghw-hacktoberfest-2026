# MLH GHW Builders Week — Tiger Data sample (Challenges 1, 3, 5)

**Event:** Global Hack Week: Builders Week, Nov 6–12, 2026  
**Scope:** Preparation only under `builders-week/tiger/` — idempotent SQL, a capped sample dataset, Tiger CLI runbook, and **mock/local** verification.  
**Live Tiger Cloud execution is not claimed here** until you run the CLI runbook against your own service with credentials.

## Challenges covered

| MLH challenge | What this folder prepares |
|---------------|---------------------------|
| **1 — Hypertable** | Import plain `device_events` CSV → `SELECT create_hypertable(...)` |
| **3 — Tiger CLI** | [`cli/RUNBOOK.md`](cli/RUNBOOK.md) — `tiger service list`, `tiger db query`, `tiger db extensions list`, etc. |
| **5 — pgvector + pgvectorscale** | Hybrid hypertable `alert_embeddings` with similarity SQL filtered by **time**, **metadata**, and **cosine / L2** distance |

Official references (read before live runs):

- [Tiger Data quickstart](https://www.tigerdata.com/docs/get-started)
- [Your first hypertable](https://www.tigerdata.com/docs/build/how-to/your-first-hypertable)
- [Tiger CLI reference](https://www.tigerdata.com/docs/reference/tiger-cloud/tiger-cli)
- [pgvector with TimescaleDB (tutorial)](https://www.tigerdata.com/learn/postgresql-extensions-pgvector)

## Layout

```
builders-week/tiger/
  sql/                 # Run in numeric order against builders_week schema
  data/                # Small labeled sample CSVs (≤ 40 rows each)
  queries/             # Verification + similarity examples (parameterized)
  cli/                 # Challenge 3 CLI runbook
  scripts/             # Local tests + optional live driver
  tests/               # MOCK — no database required
  docs/                # Submission draft text + checklist
```

## Embeddings (honest labeling)

Vectors in `data/alert_embeddings_sample.csv` are **deterministic 16-dimensional feature hashes** derived from alert text and metadata (`scripts/gen_deterministic_embeddings.py`). They exercise pgvector operators and indexes but are **not** LLM semantic embeddings. Replace with real embeddings from your chosen model when you extend this for production RAG.

## Quick start (local / mock)

```bash
cd builders-week/tiger
python3 -m unittest discover -s tests -p 'test_*.py' -q
./scripts/verify_local.sh
```

## Quick start (live Tiger Cloud — requires your account)

1. Install and authenticate: [Tiger CLI](https://www.tigerdata.com/docs/reference/tiger-cloud/tiger-cli) (`tiger auth login`).
2. Create or pick a free Tiger Cloud service ([quickstart](https://www.tigerdata.com/docs/get-started)).
3. `export TIGER_SERVICE_NAME='<your-service>'`
4. Follow [`cli/RUNBOOK.md`](cli/RUNBOOK.md), then:

```bash
./scripts/run_live.sh
```

5. Run verification queries:

```bash
tiger db query "$TIGER_SERVICE_NAME" -f queries/verify_extensions.sql
tiger db query "$TIGER_SERVICE_NAME" -f queries/verify_hypertable_chunks.sql
tiger db query "$TIGER_SERVICE_NAME" -f queries/similarity_filtered_time.sql
```

## Isolation and safety

- All objects live in schema **`builders_week`** only.
- Scripts use `IF NOT EXISTS` / `if_not_exists => TRUE` where supported.
- No `DROP DATABASE`, no destructive resets.
- `run_live.sh` exits non-zero if `TIGER_SERVICE_NAME` is unset.

## Status

See [`STATUS.md`](STATUS.md) and [`docs/SUBMISSION_DRAFTS.md`](docs/SUBMISSION_DRAFTS.md).
