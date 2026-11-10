# Tiger Challenge 3 — Tiger CLI MCP integration

Evidence that the Tiger CLI's built-in MCP server was connected from this
box over stdio, initialized, and used to list tools and call live HTTPS
management APIs against the existing Tiger Cloud service `ghw-tiger`
(`vum48trstx`).

Recorded: 2026-11-10, 3:13–3:14 PM EST (America/Detroit).

## What was integrated

The [Tiger CLI](https://github.com/timescale/tiger-cli) (`/home/box/.local/bin/tiger`,
version **0.26.0**) ships an MCP server:

```bash
tiger mcp start stdio
```

That process is a JSON-RPC MCP server on stdin/stdout. In CLI 0.26.0 the
framing is **newline-delimited JSON**, not LSP `Content-Length` headers.
Sending a `Content-Length` frame makes the server exit with:

```
invalid character 'C' looking for beginning of value
```

The small client in this directory, `mcp_client.py`, starts that server,
performs the `initialize` handshake (`protocolVersion: 2024-11-05`), sends
`notifications/initialized`, calls `tools/list`, then calls selected tools.

Authentication is the CLI's already-stored login (the same credentials used
by `tiger service list`). No extra tokens were written to disk, and nothing
was committed to the repo.

## Tools exposed (19)

`db_query`, `db_schema`, `feedback`, `search_docs`, `service_create`,
`service_delete`, `service_fork`, `service_get`, `service_list`,
`service_logs`, `service_metrics_available`, `service_metrics_details`,
`service_metrics_series`, `service_rename`, `service_resize`,
`service_start`, `service_stop`, `service_update_password`, `view_skill`.

Full names, descriptions, and input schemas: `mcp_tools_list.txt` and
`mcp_tools_list.json`.

## Calls made (and not made)

| Tool | Result |
| --- | --- |
| `service_list` | Succeeded (HTTPS). Returned `ghw-tiger` / `vum48trstx`, status `READY`. |
| `service_get` | Succeeded (HTTPS). `with_password` was forced `false`. Connection string and endpoint redacted in this evidence. Status `READY`. |
| `service_metrics_available` | Succeeded (HTTPS). Optional extra read-only call. |
| `db_query` (`select now(), version();`) | **Failed.** Direct Postgres from this box is blocked by the box proxy. Exact error (host redacted): `failed to connect to database: failed to connect to user=tsdbadmin database=tsdb: 198.18.0.1:33225 ([REDACTED_ENDPOINT]): tls error: timeout: context deadline exceeded` |

These tools were **not** called, by design: `service_start`, `service_stop`,
`service_create`, `service_delete`, `service_fork`, `service_rename`,
`service_resize`, `service_update_password`.

The service itself was resumed earlier with the ordinary CLI command
`tiger service start vum48trstx` (existing Performance trial, no new
service, card, or plan change). That start is recorded in
`service_status.txt`. The service was left **RUNNING** so the Challenge 4
console SQL can be run next; it should be paused afterwards.

## How to replay (read-only)

```bash
python3 /workspace/builders-week-prep/tiger3/mcp_client.py
```

Requires a logged-in Tiger CLI. The client only calls the read-only /
non-mutating tools listed above. Output is written back into this directory,
with passwords, tokens, connection strings, and database endpoints redacted.

## File list

- `mcp_client.py` — stdio MCP client
- `mcp_initialize.txt` — handshake request/response
- `mcp_tools_list.txt` / `mcp_tools_list.json` — `tools/list`
- `mcp_service_list.txt` — `service_list` result
- `mcp_service_get.txt` — `service_get` for `vum48trstx` (redacted)
- `mcp_query_attempt.txt` — `db_query` attempt and exact error
- `mcp_metrics_available.txt` — optional HTTPS metrics catalog
- `mcp_transcript.txt` / `mcp_summary.json` — full redacted session
- `service_status.txt` — CLI start + READY status (redacted)
- `tiger3_evidence.png` — terminal-style summary of the session
- `tiger3_tools.png` — tools list
