"""MOCK static analysis of SQL invariants (no database — not live correctness proof)."""
from __future__ import annotations

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

    def test_no_delete_or_drop_in_fixture_sql(self):
        for name in ("02_import_device_events.sql", "04b_import_alert_embeddings.sql", "04_hybrid_vector.sql"):
            text = (SQL / name).read_text(encoding="utf-8").upper()
            self.assertNotIn("DELETE FROM", text, msg=name)
            self.assertNotRegex(text, r"DROP\s+TABLE", msg=name)

    def test_fixture_uses_on_conflict(self):
        dev = (SQL / "02_import_device_events.sql").read_text(encoding="utf-8")
        alert = (SQL / "04b_import_alert_embeddings.sql").read_text(encoding="utf-8")
        self.assertIn("ON CONFLICT", dev)
        self.assertIn("DO NOTHING", dev)
        self.assertIn("ON CONFLICT", alert)

    def test_no_fixture_batch_default_on_tables(self):
        for name in ("02_table_plain.sql", "04_hybrid_vector.sql"):
            text = (SQL / name).read_text(encoding="utf-8")
            self.assertNotIn("DEFAULT 'bw2026-demo-v1'", text, msg=name)
            self.assertIn("fixture_batch TEXT NULL", text, msg=name)

    def test_typmod_check_uses_raw_atttypmod(self):
        text = (SQL / "04_hybrid_vector.sql").read_text(encoding="utf-8")
        self.assertIn("a.atttypmod INTO dim", text)
        self.assertNotIn("atttypmod - 4", text)
        self.assertIn("RAISE EXCEPTION", text)

    def test_hypertable_unique_index_includes_time(self):
        text = (SQL / "04_hybrid_vector.sql").read_text(encoding="utf-8")
        self.assertRegex(text, r"ON alert_embeddings \(recorded_at,\s*fixture_key\)")

    def test_vector_dimension_256(self):
        text = (SQL / "04_hybrid_vector.sql").read_text(encoding="utf-8")
        self.assertIn("vector(256)", text)

    def test_join_orders_by_vector_distance(self):
        text = (QUERIES / "join_timeseries_vector.sql").read_text(encoding="utf-8")
        self.assertIn("ORDER BY ae.embedding <=> q.query_vec", text)

    def test_extensions_no_silent_catch_all(self):
        text = (SQL / "01_extensions.sql").read_text(encoding="utf-8")
        self.assertNotIn("WHEN OTHERS", text)

    def test_runbook_no_free_cost_guarantee(self):
        text = (CLI / "RUNBOOK.md").read_text(encoding="utf-8")
        lower = text.lower()
        self.assertIn("billing", lower)
        self.assertIn("verify", lower)
        if "service create" in text:
            self.assertIn("--cpu shared", text)
            self.assertIn("us-east-1", text)


if __name__ == "__main__":
    unittest.main()
