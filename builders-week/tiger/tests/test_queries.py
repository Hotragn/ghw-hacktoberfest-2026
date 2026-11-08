"""MOCK — query files reference pgvector distance operators."""
from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
QUERIES = ROOT / "queries"


class TestQueries(unittest.TestCase):
    def test_similarity_operators_present(self):
        cosine = (QUERIES / "similarity_cosine.sql").read_text(encoding="utf-8")
        l2 = (QUERIES / "similarity_l2.sql").read_text(encoding="utf-8")
        self.assertIn("<=>", cosine)
        self.assertIn("<->", l2)


if __name__ == "__main__":
    unittest.main()
