"""Background worker: processes channel messages and re-embedding jobs from the durable queue.
    python -m witness.worker          (run N replicas; SKIP LOCKED keeps them from colliding)"""
from __future__ import annotations
import asyncio
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tigerkit import make_pool  # noqa: E402
from tigerprod import setup_logging  # noqa: E402
from witness import channels, jobs, llm, reembed  # noqa: E402
from witness.runtime import Agent  # noqa: E402
from witness.tools import Services  # noqa: E402


def handlers(pool, agent, senders) -> dict:
    async def channel(p: dict):
        inb = channels.Inbound(p["channel"], p["external_id"], p.get("text", ""),
                               tuple(p["approval_action"]) if p.get("approval_action") else None, p.get("message_id"))
        await channels.handle(pool, agent, inb, senders.get(inb.channel))

    async def re_embed(p: dict):
        await reembed.run(pool, int(p.get("batch", 64)))

    async def deferred(p: dict):
        """Turns parked on quota exhaustion. Web turns have no sender: the result lands in /api/v2/tasks."""
        from witness.router import QuotaExhausted
        if p.get("channel") == "web":
            try:
                await agent.run(p["user_id"], p["text"], channel="web")
            except QuotaExhausted as q:
                raise jobs.Defer(q.retry_at) from None
            return
        inb = channels.Inbound(p["channel"], p["external_id"], p.get("text", ""), None, p.get("message_id"))
        await channels.handle(pool, agent, inb, senders.get(inb.channel), deferred=True)
    return {"channel": channel, "reembed": re_embed, "deferred": deferred}


async def main():
    setup_logging()
    pool = await make_pool("witness", max_size=int(os.environ.get("WITNESS_DB_POOL", "10")))
    agent = Agent(pool, llm.from_env(pool=pool), Services())
    await jobs.Worker(pool, handlers(pool, agent, channels.senders_from_env())).run_forever()

if __name__ == "__main__":
    asyncio.run(main())
