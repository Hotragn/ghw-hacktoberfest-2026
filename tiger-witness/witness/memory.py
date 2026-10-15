"""Episodic + semantic memory in Tiger.
Episodic: witness.agent_events hypertable (every message, tool call, gate decision), rolled up by the habits_daily
continuous aggregate. Semantic: witness.memory_items with pgvector embeddings; the user can list, edit, pin and
forget any item. Forgetting is a hard DELETE plus a hash-only tombstone and a signed receipt."""
from __future__ import annotations
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from witness import embeddings  # noqa: E402

KINDS = ("fact", "preference", "person", "place", "episode")


async def _vec(conn, text: str) -> tuple[str, str, int, float]:
    """(vector literal, model id, dim, dedupe distance) for the active embedding model; ensures its ANN index."""
    e = embeddings.get()
    v = (await e.embed([text]))[0]
    await embeddings.ensure_index(conn, e)
    return embeddings.literal(v), e.model, int(e.dim), e.dedupe_distance


async def log_event(conn, user: str, kind: str, content: dict, task_id=None, tool=None, channel=None, lang=None,
                    tainted: bool = False, at: datetime | None = None) -> None:
    await conn.execute("""INSERT INTO agent_events (ts,user_id,task_id,kind,tool,channel,lang,tainted,content)
        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9::jsonb)""", at or datetime.now(timezone.utc), user, task_id, kind, tool,
                       channel, lang, tainted, json.dumps(content, default=str))


def _row(r) -> dict:
    d = dict(r)
    d.pop("embedding", None)
    d.pop("embedding_v", None)
    for k, v in d.items():
        if isinstance(v, datetime):
            d[k] = v.isoformat()
    return d


async def add(conn, user: str, text: str, kind: str = "fact", source: str = "user", data_class: str = "personal",
              confidence: float = 1.0) -> dict:
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {KINDS}")
    text = text.strip()
    vec, model, dim, dd = await _vec(conn, text)
    dup = await conn.fetchrow(f"""SELECT memory_id FROM memory_items WHERE user_id=$1 AND embed_model=$3
        AND embedding_v::vector({dim}) <=> $2::vector({dim}) < $4 LIMIT 1""", user, vec, model, dd)
    if dup:  # near-duplicate: update instead of piling up
        r = await conn.fetchrow("""UPDATE memory_items SET text=$3, embedding_v=$4::vector, updated_at=now()
            WHERE memory_id=$1 AND user_id=$2 RETURNING *""", dup["memory_id"], user, text, vec)
    else:
        r = await conn.fetchrow("""INSERT INTO memory_items (user_id,kind,text,data_class,source,confidence,embedding_v,embed_model)
            VALUES ($1,$2,$3,$4,$5,$6,$7::vector,$8) RETURNING *""", user, kind, text, data_class, source, confidence, vec, model)
    return _row(r)


async def search(conn, user: str, query: str, k: int = 5) -> list[dict]:
    vec, model, dim, _ = await _vec(conn, query)
    # dim is an int from the embedder, never user input; the cast matches the per-model partial index
    rs = await conn.fetch(f"""SELECT *, 1 - (embedding_v::vector({dim}) <=> $2::vector({dim})) AS score FROM memory_items
        WHERE user_id=$1 AND embed_model=$4 AND (expires_at IS NULL OR expires_at > now())
        ORDER BY pinned DESC, embedding_v::vector({dim}) <=> $2::vector({dim}) LIMIT $3""", user, vec, k, model)
    if rs:
        await conn.execute("UPDATE memory_items SET last_used_at=now() WHERE memory_id = ANY($1::bigint[])",
                           [r["memory_id"] for r in rs])
    return [_row(r) for r in rs]


async def list_items(conn, user: str, limit: int = 200) -> list[dict]:
    return [_row(r) for r in await conn.fetch(
        "SELECT * FROM memory_items WHERE user_id=$1 ORDER BY pinned DESC, updated_at DESC LIMIT $2", user, limit)]


async def edit(conn, user: str, memory_id: int, text: str | None = None, pinned: bool | None = None,
               kind: str | None = None) -> dict | None:
    cur = await conn.fetchrow("SELECT * FROM memory_items WHERE memory_id=$1 AND user_id=$2", memory_id, user)
    if not cur:
        return None
    t = text.strip() if text else cur["text"]
    vec, model, _, _ = await _vec(conn, t)
    r = await conn.fetchrow("""UPDATE memory_items SET text=$3, embedding_v=$4::vector, embed_model=$7, pinned=$5, kind=$6,
        source='user', confidence=1.0, updated_at=now() WHERE memory_id=$1 AND user_id=$2 RETURNING *""", memory_id, user, t,
        vec, cur["pinned"] if pinned is None else pinned, kind or cur["kind"], model)
    return _row(r)


async def forget(conn, user: str, memory_id: int) -> str | None:
    r = await conn.fetchrow("DELETE FROM memory_items WHERE memory_id=$1 AND user_id=$2 RETURNING text", memory_id, user)
    if not r:
        return None
    h = hashlib.sha256(r["text"].encode()).hexdigest()
    await conn.execute("INSERT INTO memory_forget_log (user_id,memory_id,text_sha256) VALUES ($1,$2,$3)", user, memory_id, h)
    return h


async def habits(conn, user: str, days: int = 30) -> list[dict]:
    rs = await conn.fetch("""SELECT tool, channel, sum(n)::int AS n, sum(n_tainted)::int AS n_tainted FROM my_habits
        WHERE bucket > now() - make_interval(days => $1) AND kind='tool_call' GROUP BY 1,2 ORDER BY 3 DESC""", days)
    return [dict(r) for r in rs]


async def context_for(conn, user: str, query: str, k: int = 5) -> str:
    items = await search(conn, user, query, k)
    if not items:
        return ""
    return "Known about the user (editable by them; may be outdated):\n" + "\n".join(f"- [{i['kind']}] {i['text']}" for i in items)
