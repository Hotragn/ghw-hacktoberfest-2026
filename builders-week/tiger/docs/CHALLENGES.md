# Tiger challenge mapping (Builders Week)

| ID | Official title | Requirement (paraphrase) | Artifact in this repo |
|----|----------------|--------------------------|------------------------|
| 1 | Launch Your First Tiger Data Hypertable | Free cloud instance, sample time-series import, convert standard table → hypertable | `sql/02_table_plain.sql`, `sql/02_import_device_events.sql`, `sql/03_convert_hypertable.sql`, `data/device_events_sample.csv` |
| 3 | Supercharge AI Agents with Tiger CLI or MCP | CLI **or** MCP to query/manage live DB | `cli/RUNBOOK.md`, `cli/examples.sh`, `scripts/run_live.sh` |
| 5 | Implement AI-Powered Vector Search with pgvector | pgvector + pgvectorscale, similarity with time/metadata/distance filters | `sql/04_hybrid_vector.sql`, `sql/05_indexes.sql`, `queries/similarity_*.sql` |

Parent repo Tiger projects (`tiger-tooltruth/`, etc.) are **separate** prior work; this folder is fresh Builders Week prep only.
