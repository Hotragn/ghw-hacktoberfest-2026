-- Hypertable registry + chunk summary (read-only).
SET search_path TO builders_week, public;

SELECT hypertable_schema, hypertable_name, num_dimensions, compression_enabled
FROM timescaledb_information.hypertables
WHERE hypertable_schema = 'builders_week'
ORDER BY hypertable_name;

SELECT hypertable_name, chunk_name, range_start, range_end
FROM timescaledb_information.chunks
WHERE hypertable_schema = 'builders_week'
ORDER BY hypertable_name, range_start;

SELECT count(*) AS device_event_rows FROM device_events;
SELECT count(*) AS alert_embedding_rows FROM alert_embeddings;
