"""Tiny MCP server over stdio for tests: tools `echo` (readOnly) and `post_message` (write)."""
import json
import sys

TOOLS = [
    {"name": "echo", "description": "Echo text back", "annotations": {"readOnlyHint": True},
     "inputSchema": {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}},
    {"name": "post_message", "description": "Post a message somewhere",
     "inputSchema": {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}},
]
for line in sys.stdin:
    m = json.loads(line)
    if "id" not in m:
        continue
    meth, res = m["method"], None
    if meth == "initialize":
        res = {"protocolVersion": m["params"]["protocolVersion"], "capabilities": {"tools": {}},
               "serverInfo": {"name": "fake", "version": "1"}}
    elif meth == "tools/list":
        res = {"tools": TOOLS}
    elif meth == "tools/call":
        a = m["params"]["arguments"]
        res = {"content": [{"type": "text", "text": f"{m['params']['name']}: {a.get('text', '')}"}]}
    out = {"jsonrpc": "2.0", "id": m["id"], "result": res} if res is not None else \
        {"jsonrpc": "2.0", "id": m["id"], "error": {"code": -32601, "message": "method not found"}}
    sys.stdout.write(json.dumps(out) + "\n")
    sys.stdout.flush()
