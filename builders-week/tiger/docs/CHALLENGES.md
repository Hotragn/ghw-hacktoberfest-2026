# Tiger challenge mapping

| ID | MLH title | Artifacts |
|----|-----------|-----------|
| 1 | Launch hypertable | `02_table_plain.sql`, `02_import_device_events.sql`, `03_convert_hypertable.sql`, `data/device_events_sample.csv` |
| 3 | Tiger CLI or MCP | `cli/RUNBOOK.md`, `scripts/run_live.sh` (CLI path) |
| 5 | pgvector + pgvectorscale | `04_hybrid_vector.sql`, `embed_semantic.py`, `05_indexes.sql`, `queries/similarity_*.sql` |

Challenge 5 vectors: **semantic**, 384-d, `sentence-transformers/all-MiniLM-L6-v2`.
