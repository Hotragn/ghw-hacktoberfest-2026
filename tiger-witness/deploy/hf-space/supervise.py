"""Tiny process manager for the single-container Hugging Face Space.

Runs three children and restarts any that exit (with capped backoff):
  llm     llama.cpp server on 127.0.0.1:8080 (internal only), light tier for the router
  api     uvicorn witness.api:app on 0.0.0.0:$PORT (7860, the only port HF exposes)
  worker  python -m witness.worker (jobs, deferral drain, outbound channel sends)

Before starting it runs a DB egress preflight and logs a loud, actionable error if TIGER_DB_URL
points at a port Hugging Face blocks (Spaces only allow outbound 80, 443, 8080). It never
exits on that error so /healthz still answers and the Space logs show the reason.
Standard library only, so it runs before (and independently of) the app's dependencies.
"""
from __future__ import annotations

import os
import signal
import socket
import subprocess
import sys
import time
from dataclasses import dataclass, field
from urllib.parse import urlsplit

HF_EGRESS_PORTS = frozenset({80, 443, 8080})   # https://huggingface.co/docs/hub/spaces-overview#networking


def log(msg: str) -> None:
    print(f"[supervise] {msg}", flush=True)


def db_target(url: str | None) -> tuple[str, int] | None:
    if not url:
        return None
    u = urlsplit(url)
    if not u.hostname:
        return None
    return u.hostname, u.port or 5432


def preflight_db(url: str | None, timeout: float = 5.0, connect=socket.create_connection) -> tuple[bool, str]:
    t = db_target(url)
    if t is None:
        return False, "TIGER_DB_URL is not set: add it as a Space secret (Settings > Variables and secrets)"
    host, port = t
    hint = ""
    if port not in HF_EGRESS_PORTS:
        hint = (f" Hugging Face Spaces only allow outbound ports {sorted(HF_EGRESS_PORTS)}; port {port} is likely "
                "blocked. See DEPLOY_HF.md 'Database reachability'.")
    try:
        connect((host, port), timeout=timeout).close()
    except OSError as e:
        return False, f"cannot reach database {host}:{port} ({e.__class__.__name__}: {e}).{hint}"
    return True, f"database {host}:{port} reachable"


def commands(env: dict) -> dict[str, list[str]]:
    port = env.get("PORT", "7860")
    py = env.get("PYTHON", sys.executable)
    cmds = {
        "api": [py, "-m", "uvicorn", "witness.api:app", "--host", "0.0.0.0", "--port", port,
                "--proxy-headers", "--forwarded-allow-ips=*"],
        "worker": [py, "-m", "witness.worker"],
    }
    model = env.get("LLAMA_MODEL_PATH", "/models/model.gguf")
    if env.get("WITNESS_LOCAL_LLM", "on").lower() != "off" and os.path.exists(model):
        cmds["llm"] = [env.get("LLAMA_SERVER", "/app/llama-server"), "-m", model,
                       "--host", "127.0.0.1", "--port", "8080", "--jinja",
                       "-c", env.get("LLAMA_CTX", "8192"), "-t", env.get("LLAMA_THREADS", "2"),
                       "--parallel", "1", "--cache-reuse", "256",
                       "--alias", env.get("WITNESS_LOCAL_LLM_MODEL", "qwen3-1.7b"), "--reasoning-budget", "0"]
    elif env.get("WITNESS_LOCAL_LLM", "on").lower() != "off":
        log(f"no GGUF at {model}; local llama.cpp fallback disabled (router uses cloud tiers + queue)")
    return cmds


@dataclass
class Child:
    name: str
    cmd: list[str]
    proc: subprocess.Popen | None = None
    restarts: int = 0
    started: float = 0.0


@dataclass
class Supervisor:
    cmds: dict[str, list[str]]
    max_backoff: float = 30.0
    popen: object = subprocess.Popen
    children: dict[str, Child] = field(default_factory=dict)
    stopping: bool = False

    def start(self, name: str) -> None:
        c = self.children.setdefault(name, Child(name, self.cmds[name]))
        c.proc = self.popen(c.cmd)
        c.started = time.monotonic()
        log(f"started {name} pid={c.proc.pid}")

    def backoff(self, c: Child) -> float:
        return min(self.max_backoff, 2 ** min(c.restarts, 5))

    def tick(self, now: float | None = None) -> list[str]:
        """Restart any exited child whose backoff has elapsed. Returns names restarted."""
        now = time.monotonic() if now is None else now
        out = []
        for c in self.children.values():
            if self.stopping or c.proc is None or c.proc.poll() is None:
                continue
            if now - c.started >= 60:      # it ran a while: treat as a fresh failure
                c.restarts = 0
            if now - c.started < self.backoff(c):
                continue
            log(f"{c.name} exited rc={c.proc.returncode}; restarting (#{c.restarts + 1})")
            c.restarts += 1
            self.start(c.name)
            out.append(c.name)
        return out

    def stop(self, *_):
        self.stopping = True
        for c in self.children.values():
            if c.proc and c.proc.poll() is None:
                c.proc.terminate()
        deadline = time.monotonic() + 10
        for c in self.children.values():
            if c.proc:
                try:
                    c.proc.wait(timeout=max(0.1, deadline - time.monotonic()))
                except subprocess.TimeoutExpired:
                    c.proc.kill()


def main() -> int:
    env = dict(os.environ)
    ok, msg = preflight_db(env.get("TIGER_DB_URL"))
    log(("OK: " if ok else "ERROR: ") + msg)
    sup = Supervisor(commands(env))
    signal.signal(signal.SIGTERM, lambda *a: (sup.stop(), sys.exit(0)))
    signal.signal(signal.SIGINT, lambda *a: (sup.stop(), sys.exit(0)))
    for name in ("llm", "api", "worker"):    # llm first so the router's local tier is warm sooner
        if name in sup.cmds:
            sup.start(name)
    while True:
        sup.tick()
        time.sleep(1)


if __name__ == "__main__":
    raise SystemExit(main())
