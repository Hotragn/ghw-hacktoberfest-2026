#!/usr/bin/env python3
"""Minimal stdio MCP client for the Tiger CLI MCP server (tiger mcp start stdio).

Used as Builders Week Tiger Challenge 3 evidence: initialize handshake,
tools/list, then read-only HTTPS management tools (service_list, service_get)
and one db_query attempt. Never calls service_start/stop/create/delete/fork
or service_update_password / service_rename / service_resize.
"""
from __future__ import annotations

import json
import os
import re
import select
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

TIGER = os.environ.get("TIGER_CLI", "/home/box/.local/bin/tiger")
SERVICE_ID = "vum48trstx"
OUT_DIR = Path(os.environ.get("TIGER3_OUT", "/workspace/builders-week-prep/tiger3"))
PROTOCOL = "2024-11-05"
# Destructive / mutating service tools — never invoked by this client.
BLOCKED_TOOLS = {
    "service_start",
    "service_stop",
    "service_create",
    "service_delete",
    "service_fork",
    "service_update_password",
    "service_rename",
    "service_resize",
}

ZONE = ZoneInfo("America/Detroit")


def now_label() -> str:
    return datetime.now(ZONE).strftime("%Y-%m-%d %I:%M:%S %p %Z")


def redact(text: str) -> str:
    if not text:
        return text
    text = re.sub(r"postgres(?:ql)?://[^\s\"']+", "postgresql://[REDACTED]", text)
    text = re.sub(
        r"[A-Za-z0-9._-]+\.tsdb\.cloud\.timescale\.com(?::\d+)?",
        "[REDACTED_ENDPOINT]",
        text,
    )
    text = re.sub(
        r"(?i)(\"(?:password|passwd|pwd|token|secret|api[_-]?key|connection(?:_string|String)|dsn)\"\s*:\s*)\"[^\"]*\"",
        r'\1"[REDACTED]"',
        text,
    )
    text = re.sub(
        r"(?i)((?:password|passwd|pwd|token|secret|api[_-]?key)\s*[:=]\s*)\S+",
        r"\1[REDACTED]",
        text,
    )
    return text


def pretty(obj: Any) -> str:
    return redact(json.dumps(obj, indent=2, default=str, ensure_ascii=False))


class McpClient:
    def __init__(self, proc: subprocess.Popen):
        self.proc = proc
        self._buf = b""
        self._id = 0
        self.framing: str | None = None  # "lsp" or "ndjson"
        self.stderr_chunks: list[str] = []

    def _next_id(self) -> int:
        self._id += 1
        return self._id

    def _drain_stderr(self) -> None:
        err = self.proc.stderr
        if err is None:
            return
        try:
            while True:
                r, _, _ = select.select([err], [], [], 0)
                if not r:
                    break
                chunk = os.read(err.fileno(), 65536)
                if not chunk:
                    break
                self.stderr_chunks.append(chunk.decode("utf-8", "replace"))
        except Exception:
            pass

    def send(self, obj: dict) -> None:
        # Tiger MCP (CLI 0.26.0) speaks newline-delimited JSON on stdio,
        # not LSP Content-Length framing. Content-Length headers cause:
        #   invalid character 'C' looking for beginning of value
        body = json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        assert self.proc.stdin is not None
        self.proc.stdin.write(body + b"\n")
        self.proc.stdin.flush()

    def request(self, method: str, params: dict | None = None, timeout: float = 60.0) -> dict:
        msg_id = self._next_id()
        payload: dict[str, Any] = {"jsonrpc": "2.0", "id": msg_id, "method": method}
        if params is not None:
            payload["params"] = params
        self.send(payload)
        return self.read_response(msg_id, timeout=timeout)

    def read_response(self, msg_id: int, timeout: float = 60.0) -> dict:
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(f"Timed out waiting for MCP response id={msg_id}")
            msg = self.read_message(timeout=remaining)
            # Skip notifications / unrelated messages; keep going until our id arrives.
            if msg.get("id") == msg_id or (msg.get("id") is None and "error" in msg and "method" not in msg):
                return msg
            # Log-like notifications are ignored.

    def notify(self, method: str, params: dict | None = None) -> None:
        payload: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            payload["params"] = params
        self.send(payload)

    def _read_more(self, timeout: float) -> bool:
        assert self.proc.stdout is not None
        r, _, _ = select.select([self.proc.stdout], [], [], timeout)
        if not r:
            return False
        chunk = os.read(self.proc.stdout.fileno(), 65536)
        if not chunk:
            return False
        self._buf += chunk
        return True

    def read_message(self, timeout: float) -> dict:
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                preview = redact(self._buf[:500].decode("utf-8", "replace"))
                raise TimeoutError(
                    f"Timed out waiting for MCP message after {timeout:.1f}s. "
                    f"buffer={preview!r}"
                )
            self._drain_stderr()
            if self._try_parse() is None:
                if not self._read_more(min(1.0, remaining)):
                    # process died?
                    code = self.proc.poll()
                    if code is not None:
                        err = redact("".join(self.stderr_chunks))
                        raise RuntimeError(
                            f"MCP server exited with code {code}. stderr:\n{err}"
                        )
                continue
            msg = self._try_parse()
            if msg is not None:
                # consume the parsed message from buffer
                consumed = self._consumed
                self._buf = self._buf[consumed:]
                return msg

    def _try_parse(self) -> dict | None:
        self._consumed = 0
        if not self._buf:
            return None
        # Detect framing from first non-empty bytes.
        if self.framing is None:
            stripped = self._buf.lstrip()
            if not stripped:
                return None
            if stripped.lower().startswith(b"content-length:") or stripped.lower().startswith(b"content-type:"):
                self.framing = "lsp"
            elif stripped.startswith(b"{") or stripped.startswith(b"["):
                # Could still be LSP if a BOM or we haven't seen headers; prefer NDJSON if first char is {
                # But some servers might print a log line first. If it looks like a header later...
                self.framing = "ndjson"
            else:
                # Maybe a log line then a message. If we have a newline, drop leading non-json line? Keep waiting.
                # If "Content-Length" appears later we'll detect on remaining data.
                if b"Content-Length:" in self._buf or b"content-length:" in self._buf:
                    self.framing = "lsp"
                elif b"\n" in self._buf and b"{" in self._buf:
                    self.framing = "ndjson"
                else:
                    return None

        if self.framing == "lsp":
            return self._try_parse_lsp()
        return self._try_parse_ndjson()

    def _try_parse_lsp(self) -> dict | None:
        # Allow leading noise (logs) before headers
        lower = self._buf.lower()
        idx = lower.find(b"content-length:")
        if idx < 0:
            return None
        header_end = self._buf.find(b"\r\n\r\n", idx)
        sep_len = 4
        if header_end < 0:
            header_end = self._buf.find(b"\n\n", idx)
            sep_len = 2
            if header_end < 0:
                return None
        headers = self._buf[idx:header_end].decode("ascii", "replace")
        length = None
        for line in headers.splitlines():
            if line.lower().startswith("content-length:"):
                length = int(line.split(":", 1)[1].strip())
        if length is None:
            return None
        body_start = header_end + sep_len
        body_end = body_start + length
        if len(self._buf) < body_end:
            return None
        body = self._buf[body_start:body_end]
        self._consumed = body_end
        return json.loads(body.decode("utf-8"))

    def _try_parse_ndjson(self) -> dict | None:
        # Skip leading whitespace / non-json lines
        buf = self._buf
        i = 0
        while i < len(buf) and buf[i] in b" \t\r\n":
            i += 1
        if i >= len(buf):
            return None
        # If we hit a log line, skip until newline
        if buf[i:i+1] != b"{":
            nl = buf.find(b"\n", i)
            if nl < 0:
                return None
            # drop noise
            self._buf = buf[nl + 1 :]
            return self._try_parse_ndjson() if self._buf else None
        nl = buf.find(b"\n", i)
        if nl < 0:
            # maybe a complete json object without newline yet
            try:
                obj, end = json.JSONDecoder().raw_decode(buf[i:].decode("utf-8"))
                self._consumed = i + end
                return obj
            except Exception:
                return None
        line = buf[i:nl].decode("utf-8").strip()
        self._consumed = nl + 1
        if not line:
            self._buf = buf[nl + 1 :]
            return self._try_parse_ndjson() if self._buf else None
        return json.loads(line)

    def close(self) -> None:
        try:
            if self.proc.stdin:
                self.proc.stdin.close()
        except Exception:
            pass
        try:
            self.proc.terminate()
            self.proc.wait(timeout=5)
        except Exception:
            try:
                self.proc.kill()
            except Exception:
                pass


def call_tool(client: McpClient, name: str, arguments: dict | None = None, timeout: float = 60.0) -> dict:
    if name in BLOCKED_TOOLS:
        raise RuntimeError(f"Refusing to call blocked tool: {name}")
    params: dict[str, Any] = {"name": name}
    if arguments:
        params["arguments"] = arguments
    return client.request("tools/call", params, timeout=timeout)


def extract_tool_text(resp: dict) -> str:
    """Flatten MCP tools/call result into text, redacted."""
    if "error" in resp:
        return pretty(resp)
    result = resp.get("result", resp)
    parts: list[str] = []
    if isinstance(result, dict):
        content = result.get("content")
        if isinstance(content, list):
            for item in content:
                if isinstance(item, dict) and item.get("type") == "text":
                    parts.append(item.get("text", ""))
                else:
                    parts.append(pretty(item))
        else:
            parts.append(pretty(result))
        if result.get("isError"):
            parts.insert(0, "[isError=true]")
    else:
        parts.append(pretty(result))
    return redact("\n".join(parts) if parts else pretty(resp))


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    transcript_lines: list[str] = []

    def log(line: str = "") -> None:
        transcript_lines.append(line)
        print(line, flush=True)

    log(f"Tiger MCP stdio client — started {now_label()} (America/Detroit)")
    log(f"CLI: {TIGER}")
    log(f"Command: {TIGER} mcp start stdio --analytics=false --version-check=false --color=false")
    log("Guardrails: no service_start/stop/create/delete/fork/rename/resize/update_password via MCP.")
    log("")

    proc = subprocess.Popen(
        [
            TIGER,
            "mcp",
            "start",
            "stdio",
            "--analytics=false",
            "--version-check=false",
            "--color=false",
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        bufsize=0,
    )
    client = McpClient(proc)
    # Brief wait so the server can boot; then handshake.
    time.sleep(0.3)

    try:
        log("=== 1) initialize handshake ===")
        init_params = {
            "protocolVersion": PROTOCOL,
            "capabilities": {},
            "clientInfo": {"name": "tiger3-mcp-client", "version": "1.0.0"},
        }
        log("-> initialize " + pretty(init_params))
        init_resp = client.request("initialize", init_params, timeout=30)
        log(f"framing detected: {client.framing}")
        log("<- initialize response:")
        log(pretty(init_resp))
        (OUT_DIR / "mcp_initialize.txt").write_text(
            f"Recorded: {now_label()} (America/Detroit)\n\n"
            f"Request:\n{pretty({'method': 'initialize', 'params': init_params})}\n\n"
            f"Response:\n{pretty(init_resp)}\n",
            encoding="utf-8",
        )

        client.notify("notifications/initialized")
        log("-> notifications/initialized")
        log("")

        log("=== 2) tools/list ===")
        tools_resp = client.request("tools/list", {}, timeout=30)
        log(pretty(tools_resp))
        tools = []
        if "result" in tools_resp and isinstance(tools_resp["result"], dict):
            tools = tools_resp["result"].get("tools") or []
        # Also list prompts if advertised — not required.
        tool_names = [t.get("name", "?") for t in tools]
        log(f"\nTool count: {len(tools)}")
        log("Tool names: " + ", ".join(tool_names))

        # Write a clean tools list (names + short descriptions + readOnly hints)
        lines = [
            f"Tiger MCP tools list — recorded {now_label()} (America/Detroit)",
            "Source: MCP tools/list over stdio (tiger mcp start stdio)",
            f"Server framing: {client.framing}",
            f"Tool count: {len(tools)}",
            "",
        ]
        for t in tools:
            ann = t.get("annotations") or {}
            lines.append(f"- {t.get('name')}")
            if ann.get("title"):
                lines.append(f"    title: {ann.get('title')}")
            ro = ann.get("readOnlyHint")
            dest = ann.get("destructiveHint")
            lines.append(f"    readOnlyHint: {ro}    destructiveHint: {dest}")
            desc = (t.get("description") or "").strip().splitlines()
            if desc:
                lines.append(f"    description: {desc[0][:240]}")
            schema = t.get("inputSchema") or {}
            req = schema.get("required") or []
            props = list((schema.get("properties") or {}).keys())
            if req:
                lines.append(f"    required: {', '.join(req)}")
            if props:
                lines.append(f"    properties: {', '.join(props)}")
            lines.append("")
        (OUT_DIR / "mcp_tools_list.txt").write_text("\n".join(lines), encoding="utf-8")
        (OUT_DIR / "mcp_tools_list.json").write_text(pretty(tools_resp) + "\n", encoding="utf-8")

        # 3) service_list
        log("=== 3) tools/call service_list ===")
        list_resp = call_tool(client, "service_list", {}, timeout=45)
        list_text = extract_tool_text(list_resp)
        log(list_text)
        (OUT_DIR / "mcp_service_list.txt").write_text(
            f"Recorded: {now_label()} (America/Detroit)\n"
            f"Tool: service_list\nArguments: {{}}\n\n"
            f"Result (redacted):\n{list_text}\n\n"
            f"Raw JSON-RPC (redacted):\n{pretty(list_resp)}\n",
            encoding="utf-8",
        )
        list_ok = "error" not in list_resp and not (
            isinstance(list_resp.get("result"), dict) and list_resp["result"].get("isError")
        )
        log(f"service_list succeeded: {list_ok}")
        log("")

        # 4) service_get (never with_password)
        log("=== 4) tools/call service_get ===")
        get_args = {"service_id": SERVICE_ID, "with_password": False}
        get_resp = call_tool(client, "service_get", get_args, timeout=45)
        get_text = extract_tool_text(get_resp)
        log(get_text)
        (OUT_DIR / "mcp_service_get.txt").write_text(
            f"Recorded: {now_label()} (America/Detroit)\n"
            f"Tool: service_get\n"
            f"Arguments: {pretty(get_args)}\n\n"
            f"Result (redacted):\n{get_text}\n\n"
            f"Raw JSON-RPC (redacted):\n{pretty(get_resp)}\n",
            encoding="utf-8",
        )
        get_ok = "error" not in get_resp and not (
            isinstance(get_resp.get("result"), dict) and get_resp["result"].get("isError")
        )
        log(f"service_get succeeded: {get_ok}")
        log("")

        # 5) db_query — expected to fail if direct Postgres is blocked from this box
        log("=== 5) tools/call db_query (select now(), version()) ===")
        query_args = {
            "service_id": SERVICE_ID,
            "query": "select now(), version();",
            "timeout_seconds": 20,
        }
        query_error = None
        try:
            query_resp = call_tool(client, "db_query", query_args, timeout=45)
            query_text = extract_tool_text(query_resp)
            query_ok = "error" not in query_resp and not (
                isinstance(query_resp.get("result"), dict) and query_resp["result"].get("isError")
            )
        except Exception as exc:
            query_resp = {"exception": type(exc).__name__, "message": str(exc)}
            query_text = redact(f"{type(exc).__name__}: {exc}")
            query_ok = False
            query_error = query_text
        log(query_text)
        log(f"db_query succeeded: {query_ok}")
        (OUT_DIR / "mcp_query_attempt.txt").write_text(
            f"Recorded: {now_label()} (America/Detroit)\n"
            f"Tool: db_query\n"
            f"Arguments: {pretty(query_args)}\n\n"
            f"Succeeded: {query_ok}\n\n"
            f"Result / error (redacted, exact text):\n{query_text}\n\n"
            f"Raw JSON-RPC or exception (redacted):\n{pretty(query_resp)}\n",
            encoding="utf-8",
        )
        log("")

        # Optional extra HTTPS read-only call: service_metrics_available
        log("=== 6) tools/call service_metrics_available (optional HTTPS) ===")
        try:
            met_resp = call_tool(client, "service_metrics_available", {"service_id": SERVICE_ID}, timeout=45)
            met_text = extract_tool_text(met_resp)
            met_ok = "error" not in met_resp and not (
                isinstance(met_resp.get("result"), dict) and met_resp["result"].get("isError")
            )
        except Exception as exc:
            met_resp = {"exception": type(exc).__name__, "message": str(exc)}
            met_text = redact(f"{type(exc).__name__}: {exc}")
            met_ok = False
        log(met_text[:4000])
        log(f"service_metrics_available succeeded: {met_ok}")
        (OUT_DIR / "mcp_metrics_available.txt").write_text(
            f"Recorded: {now_label()} (America/Detroit)\n"
            f"Tool: service_metrics_available\n"
            f"Arguments: {pretty({'service_id': SERVICE_ID})}\n\n"
            f"Succeeded: {met_ok}\n\n"
            f"Result / error (redacted):\n{met_text}\n\n"
            f"Raw JSON-RPC or exception (redacted):\n{pretty(met_resp)}\n",
            encoding="utf-8",
        )

        stderr = redact("".join(client.stderr_chunks).strip())
        summary = {
            "recorded": now_label(),
            "cli": TIGER,
            "transport": "stdio",
            "framing": client.framing,
            "service_id": SERVICE_ID,
            "initialize": "ok" if "result" in init_resp else "failed",
            "tools_listed": tool_names,
            "calls": {
                "service_list": "succeeded" if list_ok else "failed",
                "service_get": "succeeded" if get_ok else "failed",
                "db_query": "succeeded" if query_ok else "failed",
                "service_metrics_available": "succeeded" if met_ok else "failed",
            },
            "db_query_error": query_error or (None if query_ok else "see mcp_query_attempt.txt"),
            "blocked_tools_never_called": sorted(BLOCKED_TOOLS),
        }
        log("")
        log("=== SUMMARY ===")
        log(pretty(summary))
        if stderr:
            log("")
            log("=== server stderr (redacted) ===")
            log(stderr)
        (OUT_DIR / "mcp_transcript.txt").write_text(
            redact("\n".join(transcript_lines)) + "\n", encoding="utf-8"
        )
        (OUT_DIR / "mcp_summary.json").write_text(pretty(summary) + "\n", encoding="utf-8")
        return 0 if list_ok and get_ok else 1
    finally:
        client.close()


if __name__ == "__main__":
    sys.exit(main())
