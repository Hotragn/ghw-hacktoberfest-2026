"""Offline semantic quality check — skips if model cannot load/download."""
from __future__ import annotations

import math
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from fixtures import MODEL_ID  # noqa: E402

_MODEL = None
_MODEL_ERR: str | None = None


def _load():
    global _MODEL, _MODEL_ERR
    if _MODEL is not None or _MODEL_ERR is not None:
        return
    try:
        from sentence_transformers import SentenceTransformer

        _MODEL = SentenceTransformer(MODEL_ID)
    except Exception as exc:  # noqa: BLE001
        _MODEL_ERR = str(exc)


def _cos(a, b) -> float:
    return sum(x * y for x, y in zip(a, b))


@unittest.skipUnless(__import__("importlib").util.find_spec("sentence_transformers"), "sentence_transformers not installed")
class TestSemanticEmbeddings(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _load()
        if _MODEL is None:
            raise unittest.SkipTest(_MODEL_ERR or "model unavailable")

    def test_related_beats_unrelated(self):
        model = _MODEL
        assert model is not None
        thermal_doc = "high temperature alert threshold exceeded"
        related = "overheating critical temperature alarm"
        unrelated = "loading dock door opened for delivery"
        vecs = model.encode([thermal_doc, related, unrelated], normalize_embeddings=True)
        sim_related = _cos(vecs[0], vecs[1])
        sim_unrelated = _cos(vecs[0], vecs[2])
        self.assertGreater(
            sim_related,
            sim_unrelated,
            f"expected related>{sim_unrelated:.4f} but got {sim_related:.4f}",
        )
        self.assertTrue(math.isfinite(sim_related))


if __name__ == "__main__":
    unittest.main()
