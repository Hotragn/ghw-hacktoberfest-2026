"""MOCK — producer logic only, no database."""
from __future__ import annotations

import unittest
from datetime import datetime, timezone

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from iot_producer import (  # noqa: E402
    FIXTURE_BATCH,
    device_ids,
    fixture_key,
    synthesize_reading,
)


class TestProducer(unittest.TestCase):
    def test_device_ids(self):
        self.assertEqual(device_ids(3), ["sensor-1", "sensor-2", "sensor-3"])

    def test_fixture_key_stable(self):
        ts = datetime(2026, 11, 10, 12, 0, tzinfo=timezone.utc)
        self.assertEqual(fixture_key("sensor-1", ts), "sensor-1|2026-11-10T12:00:00+00:00")

    def test_synthesize_shape(self):
        ts = datetime(2026, 11, 10, 12, 0, tzinfo=timezone.utc)
        row = synthesize_reading("sensor-1", recorded_at=ts, rng=__import__("random").Random(0))
        self.assertEqual(row["device_id"], "sensor-1")
        self.assertEqual(row["fixture_batch"], FIXTURE_BATCH)
        self.assertIsInstance(row["celsius"], float)
        self.assertGreaterEqual(row["battery_pct"], 0)
        self.assertLessEqual(row["battery_pct"], 100)

    def test_celsius_in_sane_range(self):
        rng = __import__("random").Random(7)
        for i in range(20):
            row = synthesize_reading(f"sensor-{i}", rng=rng)
            self.assertGreater(row["celsius"], 15)
            self.assertLess(row["celsius"], 30)


if __name__ == "__main__":
    unittest.main()
