# MLH Tiger Challenge 4 — Real-time streaming analytics

**Requirement:** Live event feed (mock IoT) → Tiger Data hypertable → **continuous aggregate** → dashboard (**Streamlit**) with standard SQL insights.

## File map

| File | Purpose |
|------|---------|
| `sql/00_schema.sql` … `04_sample_readings.sql` | Schema `bw2026_stream`, hypertable, cagg `readings_1m`, idempotent seed |
| `iot_producer.py` | Mock sensor inserts at steady interval (`TIGER_DB_URL`) |
| `dashboard_app.py` | Streamlit chart over `readings_1m` |
| `tests/` | SQL static checks + producer unit tests (no DB) |
| `.env.example` | Connection placeholders only |

No `DROP` / `DELETE` in SQL. Inserts use `ON CONFLICT DO NOTHING`.

## Owner runbook

```bash
pip install -r requirements.txt
export TIGER_DB_URL=postgresql://...   # tiger db uri <service> --with-password
for f in sql/*.sql; do tiger db query "$TIGER_SERVICE_NAME" -f "$f"; done
python3 iot_producer.py --interval 2 &
streamlit run dashboard_app.py
```

Allow ~1 minute for continuous aggregate refresh policy after inserts.

## Local tests (offline)

```bash
python3 -m unittest discover -s tests -p 'test_*.py' -v
```

Does **not** validate live streaming latency or Grafana; Streamlit satisfies “dashboard” for this prep.
