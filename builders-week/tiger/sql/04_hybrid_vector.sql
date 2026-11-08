-- Challenge 5: vectors stored alongside time-series context in a hypertable.
SET search_path TO builders_week, public;

CREATE TABLE IF NOT EXISTS alert_embeddings (
  recorded_at   TIMESTAMPTZ NOT NULL,
  alert_id      BIGINT GENERATED ALWAYS AS IDENTITY,
  device_id     TEXT NOT NULL,
  site          TEXT NOT NULL,
  category      TEXT NOT NULL,
  severity      SMALLINT NOT NULL CHECK (severity BETWEEN 1 AND 5),
  summary_text  TEXT NOT NULL,
  tags          TEXT[] NOT NULL DEFAULT '{}',
  -- Deterministic demo embeddings (16-d). NOT semantic LLM vectors — see README.
  embedding     vector(16) NOT NULL
);

DO $$
BEGIN
  IF EXISTS (
    SELECT 1
    FROM timescaledb_information.hypertables
    WHERE hypertable_schema = 'builders_week'
      AND hypertable_name = 'alert_embeddings'
  ) THEN
  RAISE NOTICE 'alert_embeddings is already a hypertable';
  ELSE
    PERFORM create_hypertable(
      'builders_week.alert_embeddings',
      by_range('recorded_at', INTERVAL '7 days'),
      if_not_exists => TRUE
    );
  END IF;
END $$;

CREATE UNIQUE INDEX IF NOT EXISTS alert_embeddings_alert_id_idx ON alert_embeddings (alert_id);
CREATE INDEX IF NOT EXISTS alert_embeddings_site_sev_ts
  ON alert_embeddings (site, severity, recorded_at DESC);

-- Idempotent fixture reload for alert rows (subset tied to high-severity device events).
DELETE FROM alert_embeddings
WHERE recorded_at >= '2026-11-01 00:00:00+00'
  AND recorded_at <  '2026-11-08 00:00:00+00';

INSERT INTO alert_embeddings
  (recorded_at, device_id, site, category, severity, summary_text, tags, embedding)
VALUES
  ('2026-11-02 12:00:00+00', 'sensor-a1', 'lab-east', 'thermal', 5, 'high temperature alert threshold exceeded', ARRAY['thermal', 'critical', 'lab-east'], '[0.460147,-0.205772,0.049512,-0.098570,0.028617,0.125825,0.139452,-0.057689,0.342953,0.389285,-0.057689,-0.259372,0.181242,-0.023166,0.241202,-0.512839]'::vector),
  ('2026-11-02 12:05:00+00', 'sensor-a1', 'lab-east', 'thermal', 5, 'cooling fan failure suspected', ARRAY['thermal', 'hardware', 'lab-east'], '[0.589861,-0.175082,-0.057319,-0.294931,-0.063572,0.097963,-0.053150,-0.056277,0.198010,0.401231,-0.218853,-0.357460,-0.030223,0.174040,0.279298,-0.162577]'::vector),
  ('2026-11-04 08:02:00+00', 'sensor-a1', 'lab-east', 'power', 4, 'power quality event logged', ARRAY['power', 'lab-east'], '[0.015189,0.340491,-0.093667,-0.212648,0.039239,0.293657,0.474661,0.206320,-0.240495,0.101261,0.243027,0.113919,-0.065820,0.279734,-0.203788,-0.458207]'::vector),
  ('2026-11-01 16:45:00+00', 'sensor-b2', 'lab-east', 'physical', 4, 'door held open 90 seconds', ARRAY['access', 'lab-east'], '[-0.253113,-0.286998,0.377359,-0.137081,-0.236683,0.109357,-0.329098,0.156591,0.111411,0.216147,0.154537,-0.234630,-0.459505,0.179181,0.257220,-0.209986]'::vector),
  ('2026-11-04 14:00:00+00', 'sensor-b2', 'lab-east', 'air-quality', 3, 'co2 ppm elevated during meeting', ARRAY['co2', 'occupancy', 'lab-east'], '[0.053165,0.026116,-0.485010,-0.143637,-0.068088,0.152032,0.248101,-0.103531,-0.040107,-0.042905,-0.013991,0.368421,-0.207062,0.253697,0.583877,-0.230380]'::vector),
  ('2026-11-07 09:15:00+00', 'sensor-a1', 'lab-east', 'thermal', 3, 'soft warning below critical threshold', ARRAY['thermal', 'warning', 'lab-east'], '[0.370151,0.096737,-0.286737,-0.102530,-0.313383,0.049238,-0.289054,-0.035335,-0.090945,0.115274,0.238078,-0.158140,-0.180152,-0.114115,0.630820,-0.169725]'::vector),
  ('2026-11-03 13:40:00+00', 'sensor-a1', 'lab-east', 'thermal', 2, 'recovered after maintenance', ARRAY['thermal', 'maintenance', 'lab-east'], '[0.536123,-0.030396,0.205727,-0.216299,-0.438326,0.122907,0.123788,0.161674,0.117621,0.109692,0.057709,-0.202203,-0.238326,0.345815,0.296476,-0.198678]'::vector),
  ('2026-11-05 12:20:00+00', 'sensor-d4', 'warehouse', 'access', 2, 'loading dock opened', ARRAY['access', 'warehouse'], '[0.404487,-0.400821,0.164972,-0.417929,-0.318946,-0.080653,-0.090429,-0.282285,0.400821,0.202854,-0.108759,-0.074543,-0.208964,-0.039104,0.094095,-0.067211]'::vector),
  ('2026-11-06 15:00:00+00', 'sensor-c3', 'roof-north', 'thermal', 3, 'afternoon heat on roof sensor', ARRAY['thermal', 'roof-north', 'weather'], '[0.410451,-0.193549,0.147636,0.093014,-0.190383,0.001979,0.450031,0.453198,-0.099347,0.096972,0.120721,-0.055809,0.111221,-0.191966,0.481696,-0.035227]'::vector),
  ('2026-11-02 15:30:00+00', 'sensor-d4', 'warehouse', 'motion', 3, 'motion detected aisle 3', ARRAY['motion', 'warehouse', 'security'], '[-0.127085,-0.477469,0.020446,-0.369227,-0.257777,0.264993,0.412524,-0.143120,0.283435,0.055725,-0.217687,-0.128688,0.193634,-0.008419,0.247354,0.213678]'::vector);
