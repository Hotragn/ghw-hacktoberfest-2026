-- Load sample device events (idempotent: delete+reload only our fixture window).
SET search_path TO builders_week, public;

DELETE FROM device_events
WHERE recorded_at >= '2026-11-01 00:00:00+00'
  AND recorded_at <  '2026-11-08 00:00:00+00';

INSERT INTO device_events (recorded_at, device_id, site, event_type, severity, value_celsius, message) VALUES
  ('2026-11-01 08:15:00+00', 'sensor-a1', 'lab-east', 'temperature', 1, 21.2, 'nominal operating temperature'),
  ('2026-11-01 09:00:00+00', 'sensor-a1', 'lab-east', 'temperature', 2, 24.8, 'warmup after overnight idle'),
  ('2026-11-01 10:30:00+00', 'sensor-b2', 'lab-east', 'humidity', 1, NULL, 'relative humidity 48 percent'),
  ('2026-11-01 11:05:00+00', 'sensor-a1', 'lab-east', 'temperature', 3, 28.1, 'brief spike during calibration'),
  ('2026-11-01 14:20:00+00', 'sensor-c3', 'roof-north', 'temperature', 2, 19.5, 'external ambient reading'),
  ('2026-11-01 16:45:00+00', 'sensor-b2', 'lab-east', 'door', 4, NULL, 'door held open 90 seconds'),
  ('2026-11-02 07:10:00+00', 'sensor-a1', 'lab-east', 'temperature', 1, 20.9, 'morning baseline'),
  ('2026-11-02 08:55:00+00', 'sensor-c3', 'roof-north', 'wind', 2, NULL, 'gust 12 m/s from northwest'),
  ('2026-11-02 12:00:00+00', 'sensor-a1', 'lab-east', 'temperature', 5, 35.4, 'cooling fan failure suspected'),
  ('2026-11-02 12:05:00+00', 'sensor-a1', 'lab-east', 'alert', 5, 35.4, 'high temperature alert threshold exceeded'),
  ('2026-11-02 15:30:00+00', 'sensor-d4', 'warehouse', 'motion', 3, NULL, 'motion detected aisle 3'),
  ('2026-11-03 06:00:00+00', 'sensor-c3', 'roof-north', 'temperature', 1, 14.2, 'overnight low'),
  ('2026-11-03 09:15:00+00', 'sensor-b2', 'lab-east', 'humidity', 2, NULL, 'humidity trending up'),
  ('2026-11-03 13:40:00+00', 'sensor-a1', 'lab-east', 'temperature', 2, 23.0, 'recovered after maintenance'),
  ('2026-11-03 17:00:00+00', 'sensor-d4', 'warehouse', 'temperature', 1, 18.7, 'stable storage climate'),
  ('2026-11-04 08:00:00+00', 'sensor-a1', 'lab-east', 'power', 4, NULL, 'brief brownout detected'),
  ('2026-11-04 08:02:00+00', 'sensor-a1', 'lab-east', 'alert', 4, NULL, 'power quality event logged'),
  ('2026-11-04 11:30:00+00', 'sensor-e5', 'lab-west', 'temperature', 1, 22.0, 'new node online'),
  ('2026-11-04 14:00:00+00', 'sensor-b2', 'lab-east', 'co2', 3, NULL, 'co2 ppm elevated during meeting'),
  ('2026-11-05 07:45:00+00', 'sensor-c3', 'roof-north', 'temperature', 2, 16.1, 'sunrise warming'),
  ('2026-11-05 10:10:00+00', 'sensor-a1', 'lab-east', 'temperature', 1, 21.8, 'nominal'),
  ('2026-11-05 12:20:00+00', 'sensor-d4', 'warehouse', 'door', 2, NULL, 'loading dock opened'),
  ('2026-11-05 18:30:00+00', 'sensor-e5', 'lab-west', 'temperature', 2, 24.2, 'evening occupancy heating'),
  ('2026-11-06 09:00:00+00', 'sensor-a1', 'lab-east', 'firmware', 1, NULL, 'scheduled firmware check ok'),
  ('2026-11-06 11:00:00+00', 'sensor-b2', 'lab-east', 'humidity', 1, NULL, 'humidity normalized'),
  ('2026-11-06 15:00:00+00', 'sensor-c3', 'roof-north', 'temperature', 3, 26.8, 'afternoon heat on roof sensor'),
  ('2026-11-07 08:30:00+00', 'sensor-a1', 'lab-east', 'temperature', 1, 21.0, 'builders week demo baseline'),
  ('2026-11-07 09:15:00+00', 'sensor-a1', 'lab-east', 'alert', 3, 27.0, 'soft warning below critical threshold'),
  ('2026-11-07 10:00:00+00', 'sensor-d4', 'warehouse', 'temperature', 2, 19.1, 'slight daily drift'),
  ('2026-11-07 11:45:00+00', 'sensor-e5', 'lab-west', 'temperature', 1, 22.3, 'stable');
