"""Queue a turn durably when every LLM provider is out of quota, and drain fairly.

Fairness: a user's k-th parked turn runs at retry_at + k * WITNESS_DEFER_STAGGER_S, and workers claim in run_after
order, so one user with 40 queued messages cannot starve another user's single message after a reset."""
from __future__ import annotations
import hashlib
import os
from witness import jobs
from witness.router import eta_text

QUEUE = "deferred"


async def defer_turn(pool, user: str, payload: dict, retry_at: float, dedupe: str | None = None) -> tuple[float, int | None]:
    stagger = float(os.environ.get("WITNESS_DEFER_STAGGER_S", "20"))
    async with pool.acquire() as conn:
        n = await conn.fetchval("""SELECT count(*) FROM witness.jobs WHERE status='queued' AND queue=$1
            AND payload->>'user_id' = $2""", QUEUE, user)
        when = retry_at + n * stagger
        key = dedupe or "defer:" + hashlib.sha256(f"{user}|{payload.get('channel')}|{payload.get('text')}|"
                                                  f"{payload.get('message_id')}".encode()).hexdigest()[:32]
        jid = await jobs.enqueue(conn, QUEUE, {**payload, "user_id": user}, dedupe_key=key, run_after=when,
                                 max_attempts=int(os.environ.get("WITNESS_DEFER_MAX_ATTEMPTS", "5")))
    return when, jid


def saved_message(when: float) -> str:
    return eta_text(when)
