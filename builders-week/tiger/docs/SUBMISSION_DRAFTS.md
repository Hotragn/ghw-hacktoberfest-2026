# MLH drafts — use only after live proof

## Tiger 5 (semantic)

After you run `embed_semantic.py`, apply SQL, and capture query output:

> I stored **384-dimensional semantic embeddings** (all-MiniLM-L6-v2) in `builders_week.alert_embeddings` and ran pgvector similarity with time, metadata, and L2/cosine filters. Index type: DiskANN if `vectorscale` is installed, else HNSW (see `verify_vector_index.sql`).

Do not claim completion from CSV/unit tests alone.
