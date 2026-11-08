# MLH submission drafts (Tiger challenges) — **not submitted**

Public Tiger challenge pages do not specify a prose format. Use these as starting points after you complete **live** steps. Redact passwords and hostnames in screenshots.

## Challenge 1 — Launch Your First Tiger Data Hypertable

**Suggested evidence**

- Screenshot: Tiger Console or `tiger service list` showing your service (redacted).
- Screenshot or paste: output of `queries/verify_hypertable_chunks.sql` showing `device_events` and chunks.
- Short note: imported `data/device_events_sample.csv`, converted with `sql/03_convert_hypertable.sql`.

**Draft description (edit after live run)**

> I created a free Tiger Cloud TimescaleDB service, loaded the Builders Week `device_events` sample into schema `builders_week`, and converted the plain table to a hypertable partitioned on `recorded_at`. Chunk metadata confirms time-based partitioning is active.

## Challenge 3 — Tiger CLI or MCP

**Path chosen:** Tiger CLI (not MCP).

**Suggested evidence**

- Terminal log: `tiger auth login` success (no token pasted).
- `tiger db ping <service>` success.
- `tiger db query <service> -f queries/verify_extensions.sql` table output.

**Draft description**

> I authenticated with Tiger CLI and used `tiger db query` to apply the Builders Week SQL bundle and run read-only verification queries against my Tiger Cloud service, giving my agent workflow a documented, repeatable path to inspect hypertables and extensions without hand-copying connection strings.

## Challenge 5 — pgvector

**Suggested evidence**

- `queries/verify_extensions.sql` showing `vector` and (on Tiger Cloud) `vectorscale`.
- Output of `similarity_filtered_time.sql` and `similarity_filtered_metadata.sql` showing ranked rows with distance column.
- One line noting embeddings are deterministic demo vectors unless you swapped in a real model.

**Draft description**

> I stored 16-dimensional vectors alongside time-series alert rows in hypertable `builders_week.alert_embeddings`, enabled pgvector (and pgvectorscale DiskANN when available), and ran similarity searches filtered by time range, site metadata, and severity using both cosine (`<=>`) and L2 (`<->`) metrics in pure SQL.
