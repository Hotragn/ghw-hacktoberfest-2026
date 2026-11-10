"""MOCK static SQL checks — not live execution proof."""
from __future__ import annotations

import unittest
from pathlib import Path

SQL = Path(__file__).resolve().parents[1] / "sql"


class TestSqlInvariants(unittest.TestCase):
    def test_schema_isolated(self):
        for p in SQL.glob("*.sql"):
            text = p.read_text(encoding="utf-8")
            self.assertIn("bw2026_stream", text, msg=p.name)

    def test_no_destructive_sql(self):
        for p in SQL.glob("*.sql"):
            upper = p.read_text(encoding="utf-8").upper()
            self.assertNotIn("DELETE FROM", upper, msg=p.name)
            self.assertNotRegex(upper, r"DROP\s+TABLE", msg=p.name)

    def test_hypertable_and_cagg(self):
        ht = (SQL / "02_hypertable.sql").read_text(encoding="utf-8")
        cagg = (SQL / "03_continuous_aggregate.sql").read_text(encoding="utf-8")
        self.assertIn("create_hypertable", ht)
        self.assertIn("iot_readings", ht)
        self.assertIn("timescaledb.continuous", cagg)
        self.assertIn("readings_1m", cagg)
        self.assertIn("add_continuous_aggregate_policy", cagg)


if __name__ == "__main__":
    unittest.main()
