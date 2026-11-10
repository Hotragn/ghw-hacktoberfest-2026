# Tiger Challenge 4 — Real-time streaming analytics (prep)

Mock IoT pings → Tiger hypertable → **continuous aggregate** → minimal **Streamlit** dashboard. SQL uses isolated schema `bw2026_stream` (idempotent, no `DROP`/`DELETE`).

## Prerequisites (owner)

- Tiger Cloud service + `tiger auth login`
- `export TIGER_DB_URL='postgresql://...'` (see `.env.example`; use `tiger db uri <service> --with-password`)
- Python 3.10+ and `pip install -r requirements.txt`

## 1. Apply SQL (order matters)

```bash
cd builders-week/tiger-streaming-analytics
export TIGER_SERVICE_NAME=your-service   # optional if using TIGER_DB_URL only
for f in sql/00_schema.sql sql/01_extensions.sql sql/02_hypertable.sql \
         sql/03_continuous_aggregate.sql sql/04_sample_readings.sql; do
  tiger db query "$TIGER_SERVICE_NAME" -f "$f"
  # or: psql "$TIGER_DB_URL" -f "$f"
done
```

## 2. Start mock producer

```bash
export TIGER_DB_URL=...
python3 iot_producer.py --once          # smoke
python3 iot_producer.py --interval 2    # steady feed (Ctrl+C)
```

## 3. Dashboard

```bash
export TIGER_DB_URL=...
streamlit run dashboard_app.py
```

Open the URL shown; chart uses `readings_1m` (1-minute buckets). Allow ~1 minute for continuous aggregate refresh after inserts.

## Local mock tests (no database)

```bash
python3 -m unittest discover -s tests -p 'test_*.py' -v
```

## MLH note

Live streaming + dashboard screenshot is **owner-coordinated**; this folder is lean prep only.
