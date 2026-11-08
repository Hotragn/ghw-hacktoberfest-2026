"""MOCK checks — SQL files exist and mention builders_week schema."""
from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SQL_DIR = ROOT / "sql"
EXPECTED = [
    "00_schema.sql",
    "01_extensions.sql",
    "02_table_plain.sql",
    "02_import_device_events.sql",
    "03_convert_hypertable.sql",
    "04_hybrid_vector.sql",
    "05_indexes.sql",
]


class TestSqlFiles(unittest.TestCase):
    def test_sql_bundle_complete(self):
        found = sorted(p.name for p in SQL_DIR.glob("*.sql"))
        self.assertEqual(found, sorted(EXPECTED))

    def test_schema_isolation(self):
        for name in EXPECTED:
            text = (SQL_DIR / name).read_text(encoding="utf-8")
            if name == "01_extensions.sql":
                continue
            self.assertIn("builders_week", text)


if __name__ == "__main__":
    unittest.main()
