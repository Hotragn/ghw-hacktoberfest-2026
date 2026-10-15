"""Minimal, spec-following MCP client (JSON-RPC 2.0) for the two standard transports:
- streamable HTTP: POST JSON-RPC to the endpoint; reply is application/json or a text/event-stream; Mcp-Session-Id kept.
- stdio: spawn the server process and exchange newline-delimited JSON-RPC messages.
Only `initialize`, `tools/list` and `tools/call` are needed by the agent."""
from __future__ import annotations
import asyncio
import itertools
import json
import os
import shlex
import httpx

PROTOCOL = "2025-06-18"
CLIENT_INFO = {"name": "witness", "version": "2.0.0"}


class MCPError(RuntimeError):
    pass


class _Base:
    def __init__(self):
        self._ids = itertools.count(1)
        self.server_info: dict = {}

    async def _rpc(self, method: str, params: dict | None = None) -> dict:
        raise NotImplementedError

    async def _notify(self, method: str, params: dict | None = None) -> None:
        raise NotImplementedError

    async def initialize(self) -> dict:
        r = await self._rpc("initialize", {"protocolVersion": PROTOCOL, "capabilities": {}, "clientInfo": CLIENT_INFO})
        self.server_info = r
        await self._notify("notifications/initialized")
        return r

    async def list_tools(self) -> list[dict]:
        tools, cursor = [], None
        while True:
            r = await self._rpc("tools/list", {"cursor": cursor} if cursor else {})
            tools += r.get("tools", [])
            cursor = r.get("nextCursor")
            if not cursor:
                return tools

    async def call_tool(self, name: str, arguments: dict) -> dict:
        return await self._rpc("tools/call", {"name": name, "arguments": arguments})


def result_text(res: dict) -> str:
    parts = []
    for c in res.get("content", []):
        if c.get("type") == "text":
            parts.append(c.get("text", ""))
        else:
            parts.append(f"[{c.get('type')} content]")
    if res.get("structuredContent") is not None and not parts:
        parts.append(json.dumps(res["structuredContent"]))
    return "\n".join(parts)


class HTTPClient(_Base):
    def __init__(self, url: str, token: str | None = None, transport=None, timeout: float = 30):
        super().__init__()
        self.url = url
        self.headers = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json",
                        "MCP-Protocol-Version": PROTOCOL}
        if token:
            self.headers["Authorization"] = f"Bearer {token}"
        self.client = httpx.AsyncClient(timeout=timeout, transport=transport)

    async def _post(self, msg: dict) -> httpx.Response:
        r = await self.client.post(self.url, json=msg, headers=self.headers)
        if sid := r.headers.get("mcp-session-id"):
            self.headers["Mcp-Session-Id"] = sid
        return r

    async def _rpc(self, method, params=None):
        mid = next(self._ids)
        r = await self._post({"jsonrpc": "2.0", "id": mid, "method": method, "params": params or {}})
        if r.status_code >= 400:
            raise MCPError(f"{method}: HTTP {r.status_code}")
        if r.headers.get("content-type", "").startswith("text/event-stream"):
            for line in r.text.splitlines():
                if line.startswith("data:"):
                    m = json.loads(line[5:].strip())
                    if m.get("id") == mid:
                        return _unwrap(m)
            raise MCPError(f"{method}: no response in event stream")
        return _unwrap(r.json())

    async def _notify(self, method, params=None):
        await self._post({"jsonrpc": "2.0", "method": method, "params": params or {}})

    async def close(self):
        await self.client.aclose()


class StdioClient(_Base):
    def __init__(self, command: str, env: dict | None = None):
        super().__init__()
        self.command, self.env, self.proc = command, env, None

    async def start(self):
        args = shlex.split(self.command)
        self.proc = await asyncio.create_subprocess_exec(*args, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                                                         stderr=asyncio.subprocess.DEVNULL, env={**os.environ, **(self.env or {})})
        return self

    async def _send(self, msg):
        self.proc.stdin.write((json.dumps(msg) + "\n").encode())
        await self.proc.stdin.drain()

    async def _rpc(self, method, params=None):
        mid = next(self._ids)
        await self._send({"jsonrpc": "2.0", "id": mid, "method": method, "params": params or {}})
        while True:
            line = await asyncio.wait_for(self.proc.stdout.readline(), 30)
            if not line:
                raise MCPError("server closed stdout")
            m = json.loads(line)
            if m.get("id") == mid:
                return _unwrap(m)

    async def _notify(self, method, params=None):
        await self._send({"jsonrpc": "2.0", "method": method, "params": params or {}})

    async def close(self):
        if self.proc and self.proc.returncode is None:
            self.proc.stdin.close()
            try:
                await asyncio.wait_for(self.proc.wait(), 3)
            except asyncio.TimeoutError:
                self.proc.kill()


def _unwrap(m: dict) -> dict:
    if "error" in m:
        raise MCPError(f"{m['error'].get('code')}: {m['error'].get('message')}")
    return m.get("result", {})


async def connect(transport: str, target: str, auth_env: str | None = None, http_transport=None):
    if transport == "http":
        c = HTTPClient(target, os.environ.get(auth_env) if auth_env else None, transport=http_transport)
    elif transport == "stdio":
        if os.environ.get("WITNESS_ALLOW_STDIO_MCP", "false").lower() != "true":
            raise MCPError("stdio MCP servers are disabled (set WITNESS_ALLOW_STDIO_MCP=true on trusted deployments)")
        c = await StdioClient(target).start()
    else:
        raise MCPError("unknown transport")
    await c.initialize()
    return c
