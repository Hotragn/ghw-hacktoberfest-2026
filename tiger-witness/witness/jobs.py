"""Durable Postgres job queue. Producers INSERT (dedupe_key makes webhook retries no-ops) and NOTIFY; workers claim
one job at a time with UPDATE ... WHERE job_id = (SELECT ... FOR UPDATE SKIP LOCKED LIMIT 1), so any number of
workers can run concurrently without double-processing. Failures retry with exponential backoff, then go 'dead'
(dead-letter, visible for replay). A reaper requeues jobs whose worker died mid-flight."""
from __future__ import annotations
import asyncio
import json
import logging
import os
import socket
import traceback
from typing import Awaitable, Callable

log = logging.getLogger("witness.jobs")
CHANNEL = "witness_jobs"


async def enqueue(conn, queue: str, payload: dict, dedupe_key: str | None = None, max_attempts: int = 5) -> int | None:
    jid = await conn.fetchval("""INSERT INTO witness.jobs (queue,payload,dedupe_key,max_attempts) VALUES ($1,$2::jsonb,$3,$4)
        ON CONFLICT (dedupe_key) DO NOTHING RETURNING job_id""", queue, json.dumps(payload, default=str), dedupe_key, max_attempts)
    if jid:
        await conn.execute("SELECT pg_notify($1, $2)", CHANNEL, queue)
    return jid


async def claim(pool, queues: list[str], worker_id: str):
    return await pool.fetchrow("""UPDATE witness.jobs SET status='running', locked_at=now(), locked_by=$2, attempts=attempts+1
        WHERE job_id = (SELECT job_id FROM witness.jobs WHERE status='queued' AND queue = ANY($1::text[]) AND run_after <= now()
                        ORDER BY run_after, job_id FOR UPDATE SKIP LOCKED LIMIT 1)
        RETURNING *""", queues, worker_id)


async def complete(pool, job_id: int) -> None:
    await pool.execute("UPDATE witness.jobs SET status='done', done_at=now(), locked_at=NULL, last_error=NULL WHERE job_id=$1", job_id)


async def fail(pool, job, err: str) -> str:
    dead = job["attempts"] >= job["max_attempts"]
    await pool.execute("""UPDATE witness.jobs SET status=$2, locked_at=NULL, last_error=$3,
        run_after = now() + make_interval(secs => least(300, power(2, attempts))) WHERE job_id=$1""",
                       job["job_id"], "dead" if dead else "queued", err[:2000])
    return "dead" if dead else "retry"


async def reap_stale(pool, older_than_s: int = 300) -> int:
    r = await pool.execute("""UPDATE witness.jobs SET status='queued', locked_at=NULL, locked_by=NULL
        WHERE status='running' AND locked_at < now() - make_interval(secs => $1)""", older_than_s)
    return int(r.split()[-1])


class Worker:
    def __init__(self, pool, handlers: dict[str, Callable[[dict], Awaitable[None]]], worker_id: str | None = None):
        self.pool, self.handlers = pool, handlers
        self.id = worker_id or f"{socket.gethostname()}:{os.getpid()}"
        self._wake = asyncio.Event()

    async def run_once(self) -> bool:
        job = await claim(self.pool, list(self.handlers), self.id)
        if not job:
            return False
        try:
            await self.handlers[job["queue"]](json.loads(job["payload"]))
            await complete(self.pool, job["job_id"])
        except Exception as e:  # noqa: BLE001
            outcome = await fail(self.pool, job, f"{type(e).__name__}: {e}\n{traceback.format_exc(limit=3)}")
            log.warning("job %s %s failed (%s): %s", job["job_id"], job["queue"], outcome, e)
        return True

    async def drain(self, limit: int = 1000) -> int:
        n = 0
        while n < limit and await self.run_once():
            n += 1
        return n

    async def run_forever(self, poll_s: float = 2.0) -> None:
        conn = await self.pool.acquire()
        def cb(*_):
            self._wake.set()
        await conn.add_listener(CHANNEL, cb)
        try:
            while True:
                await reap_stale(self.pool)
                while await self.run_once():
                    pass
                self._wake.clear()
                try:
                    await asyncio.wait_for(self._wake.wait(), poll_s)
                except asyncio.TimeoutError:
                    pass
        finally:
            await conn.remove_listener(CHANNEL, cb)
            await self.pool.release(conn)
