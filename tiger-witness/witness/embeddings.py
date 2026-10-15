"""Pluggable embedding providers for semantic memory.

  WITNESS_EMBEDDINGS=openai  -> any OpenAI-compatible /embeddings endpoint (WITNESS_EMBED_BASE_URL, _API_KEY, _MODEL, _DIM)
  WITNESS_EMBEDDINGS=local   -> open-source model run in-process with fastembed (ONNX, CPU):
                                sentence-transformers/all-MiniLM-L6-v2, 384-d (default when no key is configured)
  WITNESS_EMBEDDINGS=hashed  -> keyless hashed bag-of-words, 256-d. Test-only fallback; never the production default.
Each stored vector records its model; queries only compare vectors of the same model, and `python -m witness.reembed`
migrates rows to the active model (the per-model ANN index is created by witness.ensure_embedding_index)."""
from __future__ import annotations
import asyncio
import os
import sys
from typing import Protocol
import httpx
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tigerkit import text_embedding, vec_literal  # noqa: E402

LOCAL_DEFAULT = "sentence-transformers/all-MiniLM-L6-v2"


class Embedder(Protocol):
    model: str          # stable id stored with each vector
    dim: int
    dedupe_distance: float

    async def embed(self, texts: list[str]) -> list[list[float]]: ...


class HashedEmbedder:
    model, dim, dedupe_distance = "hashed-256", 256, 0.08

    async def embed(self, texts):
        return [text_embedding(t, 256) for t in texts]


class LocalEmbedder:
    """fastembed ONNX runtime; model files are cached under WITNESS_MODEL_CACHE (downloaded once from Hugging Face)."""
    _models: dict = {}
    dedupe_distance = 0.05

    def __init__(self, name: str = LOCAL_DEFAULT):
        from fastembed import TextEmbedding
        if name not in self._models:
            self._models[name] = TextEmbedding(model_name=name, cache_dir=os.environ.get("WITNESS_MODEL_CACHE"))
        self._m = self._models[name]
        self.model = "local:" + name
        self.dim = len(next(iter(self._m.embed(["dim probe"]))))

    async def embed(self, texts):
        return await asyncio.to_thread(lambda: [v.tolist() for v in self._m.embed(list(texts))])


class OpenAIEmbedder:
    dedupe_distance = 0.05

    def __init__(self, base_url: str, api_key: str, model: str, dim: int | None = None, transport=None):
        self.base, self.key, self._name, self._dim = base_url.rstrip("/"), api_key, model, dim
        self.model = "openai:" + model + (f":{dim}" if dim else "")
        self.dim = dim or 0
        self.client = httpx.AsyncClient(timeout=30, transport=transport)

    async def embed(self, texts):
        body = {"model": self._name, "input": list(texts)}
        if self._dim:
            body["dimensions"] = self._dim
        r = await self.client.post(f"{self.base}/embeddings", json=body, headers={"Authorization": f"Bearer {self.key}"})
        r.raise_for_status()
        out = [d["embedding"] for d in sorted(r.json()["data"], key=lambda d: d["index"])]
        self.dim = len(out[0])
        return out


_current: Embedder | None = None


def get() -> Embedder:
    global _current
    if _current is None:
        _current = from_env()
    return _current


def set_current(e: Embedder | None) -> None:
    global _current
    _current = e


def from_env() -> Embedder:
    kind = os.environ.get("WITNESS_EMBEDDINGS", "").lower()
    if kind == "hashed":
        return HashedEmbedder()
    if kind == "openai" or (not kind and os.environ.get("WITNESS_EMBED_API_KEY")):
        dim = os.environ.get("WITNESS_EMBED_DIM")
        return OpenAIEmbedder(os.environ.get("WITNESS_EMBED_BASE_URL", "https://api.openai.com/v1"),
                              os.environ["WITNESS_EMBED_API_KEY"], os.environ.get("WITNESS_EMBED_MODEL", "text-embedding-3-small"),
                              int(dim) if dim else None)
    return LocalEmbedder(os.environ.get("WITNESS_EMBED_LOCAL_MODEL", LOCAL_DEFAULT))


def literal(v: list[float]) -> str:
    return vec_literal(v)


_ensured: set = set()


async def ensure_index(conn, e: Embedder) -> None:
    if e.model not in _ensured:
        await conn.execute("SELECT witness.ensure_embedding_index($1, $2)", e.model, int(e.dim))
        _ensured.add(e.model)
