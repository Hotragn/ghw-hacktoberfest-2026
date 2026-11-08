"""MOCK unit tests — deterministic embedding helper (no database)."""
from __future__ import annotations

import math
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from gen_deterministic_embeddings import DIM, ROWS, embed_text, vec_literal  # noqa: E402


class TestEmbeddings(unittest.TestCase):
    def test_dimension_and_normalized(self):
        v = embed_text(
            "high temperature alert",
            site="lab-east",
            category="thermal",
            severity=5,
            device_id="sensor-a1",
        )
        self.assertEqual(len(v), DIM)
        self.assertGreaterEqual(DIM, 256)
        norm = math.sqrt(sum(x * x for x in v))
        self.assertAlmostEqual(norm, 1.0, places=4)

    def test_stable_hash(self):
        kwargs = dict(site="lab-east", category="thermal", severity=5, device_id="sensor-a1")
        a = embed_text("cooling fan failure suspected", **kwargs)
        b = embed_text("cooling fan failure suspected", **kwargs)
        self.assertEqual(a, b)

    def test_rows_produce_parseable_literal(self):
        for row in ROWS:
            _ts, dev, site, cat, sev, summary, _tags = row
            v = embed_text(summary, site=site, category=cat, severity=int(sev), device_id=dev)
            lit = vec_literal(v)
            self.assertTrue(lit.startswith("[") and lit.endswith("]"))
            self.assertEqual(len(v), 256)


if __name__ == "__main__":
    unittest.main()
