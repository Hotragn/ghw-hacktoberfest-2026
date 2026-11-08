-- Load demo fixture rows only — no DELETE; skip duplicates on (recorded_at, fixture_key).
SET search_path TO builders_week, public;

INSERT INTO device_events
  (recorded_at, fixture_key, device_id, site, event_type, severity, value_celsius, message, fixture_batch)
VALUES
  ('2026-11-01 08:15:00+00', 'sensor-a1|2026-11-01T08:15:00+00:00', 'sensor-a1', 'lab-east', 'temperature', 1, 21.2, 'nominal operating temperature', 'bw2026-demo-v1'),
  ('2026-11-01 09:00:00+00', 'sensor-a1|2026-11-01T09:00:00+00:00', 'sensor-a1', 'lab-east', 'temperature', 2, 24.8, 'warmup after overnight idle', 'bw2026-demo-v1'),
  ('2026-11-01 10:30:00+00', 'sensor-b2|2026-11-01T10:30:00+00:00', 'sensor-b2', 'lab-east', 'humidity', 1, NULL, 'relative humidity 48 percent', 'bw2026-demo-v1'),
  ('2026-11-01 11:05:00+00', 'sensor-a1|2026-11-01T11:05:00+00:00', 'sensor-a1', 'lab-east', 'temperature', 3, 28.1, 'brief spike during calibration', 'bw2026-demo-v1'),
  ('2026-11-01 14:20:00+00', 'sensor-c3|2026-11-01T14:20:00+00:00', 'sensor-c3', 'roof-north', 'temperature', 2, 19.5, 'external ambient reading', 'bw2026-demo-v1'),
  ('2026-11-01 16:45:00+00', 'sensor-b2|2026-11-01T16:45:00+00:00', 'sensor-b2', 'lab-east', 'door', 4, NULL, 'door held open 90 seconds', 'bw2026-demo-v1'),
  ('2026-11-02 07:10:00+00', 'sensor-a1|2026-11-02T07:10:00+00:00', 'sensor-a1', 'lab-east', 'temperature', 1, 20.9, 'morning baseline', 'bw2026-demo-v1'),
  ('2026-11-02 08:55:00+00', 'sensor-c3|2026-11-02T08:55:00+00:00', 'sensor-c3', 'roof-north', 'wind', 2, NULL, 'gust 12 m/s from northwest', 'bw2026-demo-v1'),
  ('2026-11-02 12:00:00+00', 'sensor-a1|2026-11-02T12:00:00+00:00', 'sensor-a1', 'lab-east', 'temperature', 5, 35.4, 'cooling fan failure suspected', 'bw2026-demo-v1'),
  ('2026-11-02 12:05:00+00', 'sensor-a1|2026-11-02T12:05:00+00:00', 'sensor-a1', 'lab-east', 'alert', 5, 35.4, 'high temperature alert threshold exceeded', 'bw2026-demo-v1'),
  ('2026-11-02 15:30:00+00', 'sensor-d4|2026-11-02T15:30:00+00:00', 'sensor-d4', 'warehouse', 'motion', 3, NULL, 'motion detected aisle 3', 'bw2026-demo-v1'),
  ('2026-11-03 06:00:00+00', 'sensor-c3|2026-11-03T06:00:00+00:00', 'sensor-c3', 'roof-north', 'temperature', 1, 14.2, 'overnight low', 'bw2026-demo-v1'),
  ('2026-11-03 09:15:00+00', 'sensor-b2|2026-11-03T09:15:00+00:00', 'sensor-b2', 'lab-east', 'humidity', 2, NULL, 'humidity trending up', 'bw2026-demo-v1'),
  ('2026-11-03 13:40:00+00', 'sensor-a1|2026-11-03T13:40:00+00:00', 'sensor-a1', 'lab-east', 'temperature', 2, 23.0, 'recovered after maintenance', 'bw2026-demo-v1'),
  ('2026-11-03 17:00:00+00', 'sensor-d4|2026-11-03T17:00:00+00:00', 'sensor-d4', 'warehouse', 'temperature', 1, 18.7, 'stable storage climate', 'bw2026-demo-v1'),
  ('2026-11-04 08:00:00+00', 'sensor-a1|2026-11-04T08:00:00+00:00', 'sensor-a1', 'lab-east', 'power', 4, NULL, 'brief brownout detected', 'bw2026-demo-v1'),
  ('2026-11-04 08:02:00+00', 'sensor-a1|2026-11-04T08:02:00+00:00', 'sensor-a1', 'lab-east', 'alert', 4, NULL, 'power quality event logged', 'bw2026-demo-v1'),
  ('2026-11-04 11:30:00+00', 'sensor-e5|2026-11-04T11:30:00+00:00', 'sensor-e5', 'lab-west', 'temperature', 1, 22.0, 'new node online', 'bw2026-demo-v1'),
  ('2026-11-04 14:00:00+00', 'sensor-b2|2026-11-04T14:00:00+00:00', 'sensor-b2', 'lab-east', 'co2', 3, NULL, 'co2 ppm elevated during meeting', 'bw2026-demo-v1'),
  ('2026-11-05 07:45:00+00', 'sensor-c3|2026-11-05T07:45:00+00:00', 'sensor-c3', 'roof-north', 'temperature', 2, 16.1, 'sunrise warming', 'bw2026-demo-v1'),
  ('2026-11-05 10:10:00+00', 'sensor-a1|2026-11-05T10:10:00+00:00', 'sensor-a1', 'lab-east', 'temperature', 1, 21.8, 'nominal', 'bw2026-demo-v1'),
  ('2026-11-05 12:20:00+00', 'sensor-d4|2026-11-05T12:20:00+00:00', 'sensor-d4', 'warehouse', 'door', 2, NULL, 'loading dock opened', 'bw2026-demo-v1'),
  ('2026-11-05 18:30:00+00', 'sensor-e5|2026-11-05T18:30:00+00:00', 'sensor-e5', 'lab-west', 'temperature', 2, 24.2, 'evening occupancy heating', 'bw2026-demo-v1'),
  ('2026-11-06 09:00:00+00', 'sensor-a1|2026-11-06T09:00:00+00:00', 'sensor-a1', 'lab-east', 'firmware', 1, NULL, 'scheduled firmware check ok', 'bw2026-demo-v1'),
  ('2026-11-06 11:00:00+00', 'sensor-b2|2026-11-06T11:00:00+00:00', 'sensor-b2', 'lab-east', 'humidity', 1, NULL, 'humidity normalized', 'bw2026-demo-v1'),
  ('2026-11-06 15:00:00+00', 'sensor-c3|2026-11-06T15:00:00+00:00', 'sensor-c3', 'roof-north', 'temperature', 3, 26.8, 'afternoon heat on roof sensor', 'bw2026-demo-v1'),
  ('2026-11-07 08:30:00+00', 'sensor-a1|2026-11-07T08:30:00+00:00', 'sensor-a1', 'lab-east', 'temperature', 1, 21.0, 'builders week demo baseline', 'bw2026-demo-v1'),
  ('2026-11-07 09:15:00+00', 'sensor-a1|2026-11-07T09:15:00+00:00', 'sensor-a1', 'lab-east', 'alert', 3, 27.0, 'soft warning below critical threshold', 'bw2026-demo-v1'),
  ('2026-11-07 10:00:00+00', 'sensor-d4|2026-11-07T10:00:00+00:00', 'sensor-d4', 'warehouse', 'temperature', 2, 19.1, 'slight daily drift', 'bw2026-demo-v1'),
  ('2026-11-07 11:45:00+00', 'sensor-e5|2026-11-07T11:45:00+00:00', 'sensor-e5', 'lab-west', 'temperature', 1, 22.3, 'stable', 'bw2026-demo-v1')
ON CONFLICT (recorded_at, fixture_key) WHERE fixture_key IS NOT NULL
DO NOTHING;
