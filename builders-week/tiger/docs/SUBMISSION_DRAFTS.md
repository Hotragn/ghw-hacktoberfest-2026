# MLH submission drafts (Tiger challenges) — **do not submit until live proof exists**

Use only after **you** complete live steps. These are conditional templates, not completion claims.

## Challenge 1 — Hypertable

**After live run, you might write:**

> I used a Tiger Cloud service, loaded fixture batch `bw2026-demo-v1` into `builders_week.device_events`, and converted the nonempty plain table with `create_hypertable(..., migrate_data => TRUE)`. Chunk metadata confirmed time partitioning.

## Challenge 3 — Tiger CLI

> I used Tiger CLI (`tiger db query -f ...`) to apply the SQL bundle and read-only verification queries against my service.

## Challenge 5 — pgvector

> I stored **256-dimensional** vectors in `builders_week.alert_embeddings` and ran similarity SQL with time, metadata, and cosine/L2 filters.

**If still using bundled hashes, add honestly:**

> Embeddings are deterministic lexical hashes for SQL/index exercises, not semantic model outputs. pgvectorscale was confirmed via `verify_extensions.sql` and `verify_vector_index.sql` (or note HNSW-only fallback).
