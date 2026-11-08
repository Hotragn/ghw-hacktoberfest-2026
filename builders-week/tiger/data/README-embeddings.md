# Embeddings in this sample

## Default (committed)

- **256-dimensional** vectors from `scripts/gen_deterministic_embeddings.py`
- Method: **lexical feature hashing** (character trigrams + salted per-dimension hashes)
- **NON-SEMANTIC** — does not use any ML model or API; does **not** satisfy “AI semantic embedding” completion by itself
- Regenerate: `python3 scripts/gen_deterministic_embeddings.py` (updates CSV, `sql/04b_*.sql`, and `queries/similarity_*.sql`)

## Optional external embeddings

You may replace fixtures with a **vetted CSV** from your own offline embedding pipeline:

```bash
python3 scripts/validate_embedding_csv.py path/to/your.csv
```

Required `embedding` width: **256** (or pass `--dim` if you change schema consistently). Never commit secrets or API keys.
