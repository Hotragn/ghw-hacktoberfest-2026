"""MOCK static analysis of SQL invariants (no database)."""
from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SQL = ROOT / "sql"
QUERIES = ROOT / "queries"
CLI = ROOT / "cli"


class TestSqlInvariants(unittest.TestCase):
    def test_migrate_data_on_device_events(self):
        text = (SQL / "03_convert_hypertable.sql").read_text(encoding="utf-8")
        self.assertIn("migrate_data => TRUE", text)

    def test_device_import_scoped_delete(self):
        text = (SQL / "02_import_device_events.sql").read_text(encoding="utf-8")
        self.assertIn("fixture_batch = 'bw2026-demo-v1'", text)
        self.assertNotRegex(text, r"DELETE FROM device_events\s+WHERE recorded_at >=")

    def test_alert_import_scoped_delete(self):
        text = (SQL / "04b_import_alert_embeddings.sql").read_text(encoding="utf-8")
        self.assertIn("fixture_batch = 'bw2026-demo-v1'", text)
        self.assertNotRegex(text, r"DELETE FROM alert_embeddings\s+WHERE recorded_at >=")

    def test_hypertable_unique_index_includes_time(self):
        text = (SQL / "04_hybrid_vector.sql").read_text(encoding="utf-8")
        self.assertRegex(text, r"ON alert_embeddings \(recorded_at,\s*fixture_key\)")
        self.assertNotRegex(text, r"UNIQUE.*\(alert_id\)")

    def test_vector_dimension_256(self):
        text = (SQL / "04_hybrid_vector.sql").read_text(encoding="utf-8")
        self.assertIn("vector(256)", text)
        self.assertNotIn("vector(16)", text)

    def test_join_orders_by_vector_distance(self):
        text = (QUERIES / "join_timeseries_vector.sql").read_text(encoding="utf-8")
        self.assertIn("ORDER BY ae.embedding <=> q.query_vec", text)
        self.assertNotIn("ORDER BY ae.recorded_at\n  LIMIT 1", text)

    def test_extensions_no_silent_catch_all(self):
        text = (SQL / "01_extensions.sql").read_text(encoding="utf-8")
        self.assertNotIn("WHEN OTHERS", text)

    def test_runbook_free_service_flags_or_no_create(self):
        text = (CLI / "RUNBOOK.md").read_text(encoding="utf-8")
        if "service create" in text:
            self.assertIn("--cpu shared", text)
            self.assertIn("--memory shared", text)
            self.assertIn("us-east-1", text)


if __name__ == "__main__":
    unittest.main()
