# MLH Builders Week — Tiger Data (`builders_week` schema)

**Event:** GHW Builders Week · **Repo path:** `builders-week/tiger/`  
**Status:** Prep + local semantic embed tests — **live Tiger Cloud not claimed** unless you run the runbook.

## Challenge map (MLH)

| MLH # | Requirement | This folder |
|-------|-------------|-------------|
| **1** Hypertable | Import sample time-series, convert plain table → hypertable | `sql/02_*`, `03_convert_hypertable.sql` (`migrate_data => TRUE`) |
| **3** Tiger CLI | Documented CLI to apply SQL / queries | `cli/RUNBOOK.md`, `scripts/run_live.sh` |
| **5** pgvector | Semantic vectors + time/metadata/distance filters; pgvectorscale DiskANN or HNSW | `sql/04_*`, `05_indexes.sql`, `queries/similarity_*.sql` |

## Challenge 5 embeddings (semantic)

| Item | Detail |
|------|--------|
| Model | `sentence-transformers/all-MiniLM-L6-v2` (384-d) |
| Script | `python3 scripts/embed_semantic.py` (after `pip install -r requirements-embed.txt`) |
| Storage | `vector(384)` in hypertable `alert_embeddings` |

No paid embedding API. First run may download the model from Hugging Face.

## Quick start (local mock)

```bash
cd builders-week/tiger
pip install -r requirements-embed.txt   # optional for semantic tests + regen
python3 scripts/embed_semantic.py      # regenerate 04b + queries
python3 -m unittest discover -s tests -p 'test_*.py' -v
./scripts/verify_local.sh
```

Static/SQL unit tests **do not** prove live hypertable or DiskANN behavior.

## Live Tiger Cloud (owner)

1. `export TIGER_DB_URL` or `TIGER_SERVICE_NAME` — see `.env.example`
2. `python3 scripts/embed_semantic.py`
3. `./scripts/run_live.sh`
4. `tiger db query ... -f queries/similarity_filtered_metadata.sql` (redact secrets in screenshots)

Billing/plan: see `cli/RUNBOOK.md` — shared CPU flags are not a zero-cost guarantee.

## Layout

```
sql/00–05, 04b_import_alert_embeddings.sql (generated)
scripts/embed_semantic.py, fixtures.py, validate_embedding_csv.py
queries/verify_*.sql, similarity_*.sql (query literals generated)
cli/RUNBOOK.md
data/device_events_sample.csv, alert_embeddings_sample.csv
tests/   SQL invariants + optional semantic quality test
```

See also: [`docs/CHALLENGES.md`](docs/CHALLENGES.md), [`data/README-embeddings.md`](data/README-embeddings.md), [`STATUS.md`](STATUS.md).
