"""MOCK checks — SQL files exist and mention builders_week schema."""
from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SQL_DIR = ROOT / "sql"
REQUIRED = {
    "00_schema.sql",
    "01_extensions.sql",
    "02_table_plain.sql",
    "02_import_device_events.sql",
    "03_convert_hypertable.sql",
    "04_hybrid_vector.sql",
    "04b_import_alert_embeddings.sql",
    "05_indexes.sql",
}


class TestSqlFiles(unittest.TestCase):
    def test_sql_bundle_complete(self):
        found = {p.name for p in SQL_DIR.glob("*.sql")}
        missing = REQUIRED - found
        self.assertFalse(missing, f"missing sql files: {sorted(missing)}")

    def test_schema_isolation(self):
        for name in REQUIRED:
            if name in ("01_extensions.sql", "04b_import_alert_embeddings.sql"):
                continue
            text = (SQL_DIR / name).read_text(encoding="utf-8")
            self.assertIn("builders_week", text)


if __name__ == "__main__":
    unittest.main()
