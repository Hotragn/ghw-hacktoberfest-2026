# Tiger sample — status

## Local (this branch)

- Challenges **1/3/5** SQL + CLI runbook
- Challenge **5:** **384-d semantic** embeddings via `all-MiniLM-L6-v2` (`embed_semantic.py`)
- Mock tests: SQL invariants + optional semantic similarity test (skips if model missing)
- Idempotent fixtures: `ON CONFLICT` only — no `DROP`/`DELETE` in bundle

## Not claimed without owner live run

- Tiger Cloud hypertable/cagg refresh proof
- pgvectorscale DiskANN on your service (fallback HNSW is SQL-only prep)
- MLH submissions

## Regenerate embeddings

```bash
pip install -r requirements-embed.txt
python3 scripts/embed_semantic.py
```
