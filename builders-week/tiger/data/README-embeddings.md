# Embeddings (Challenge 5)

| Property | Value |
|----------|--------|
| Model | `sentence-transformers/all-MiniLM-L6-v2` (384 dimensions) |
| Runtime | Local CPU; downloads once from Hugging Face (no paid embedding API) |
| Regenerate | `pip install -r requirements-embed.txt && python3 scripts/embed_semantic.py` |

Generated artifacts:

- `alert_embeddings_sample.csv`
- `sql/04b_import_alert_embeddings.sql`
- `data/query_vectors.json` + `queries/similarity_*.sql`

Validate external CSV (same schema): `python3 scripts/validate_embedding_csv.py your.csv`
