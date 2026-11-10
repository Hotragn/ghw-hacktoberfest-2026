"""MOCK unit tests for embedding CSV validator (finite numeric checks)."""
from __future__ import annotations

import math
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from validate_embedding_csv import parse_vector_literal  # noqa: E402
from fixtures import DIM  # noqa: E402


class TestParseVectorLiteral(unittest.TestCase):
    def test_valid_unit_vector(self):
        coords = ",".join("0.0" for _ in range(DIM))
        v = parse_vector_literal(f"[{coords}]", DIM)
        self.assertEqual(len(v), DIM)

    def test_rejects_dot_only(self):
        with self.assertRaises(ValueError):
            parse_vector_literal("[" + ",".join(["."] * DIM) + "]", DIM)

    def test_rejects_overflow(self):
        with self.assertRaises(ValueError):
            parse_vector_literal("[" + ",".join(["1e999"] * DIM) + "]", DIM)

    def test_rejects_nan_inf_strings(self):
        for bad in ("nan", "inf", "-inf"):
            with self.assertRaises(ValueError):
                parse_vector_literal(f"[{bad}," + "0.0," * (DIM - 1) + "0.0]", DIM)

    def test_rejects_wrong_dimension(self):
        with self.assertRaises(ValueError):
            parse_vector_literal("[1.0,2.0]", DIM)

    def test_accepts_scientific_finite(self):
        lit = "[" + ",".join(["1e-6"] * DIM) + "]"
        v = parse_vector_literal(lit, DIM)
        self.assertTrue(all(math.isfinite(x) for x in v))


if __name__ == "__main__":
    unittest.main()
