"""deploy/hf-space: process manager, DB egress preflight, Space metadata, Dockerfile invariants, CF Worker."""
import importlib.util
import os
import re
import shutil
import subprocess
import sys

import pytest
import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HF = os.path.join(ROOT, "deploy", "hf-space")
spec = importlib.util.spec_from_file_location("supervise", os.path.join(HF, "supervise.py"))
sup = importlib.util.module_from_spec(spec)
sys.modules["supervise"] = sup
spec.loader.exec_module(sup)


def test_db_target_parses_tiger_url():
    assert sup.db_target("postgres://u:p@svc.prj.tsdb.cloud.timescale.com:31234/tsdb?sslmode=require") == \
        ("svc.prj.tsdb.cloud.timescale.com", 31234)
    assert sup.db_target("postgresql://u@h/db") == ("h", 5432)
    assert sup.db_target("") is None and sup.db_target(None) is None


def test_preflight_reports_missing_blocked_and_ok():
    ok, msg = sup.preflight_db(None)
    assert not ok and "TIGER_DB_URL" in msg

    def refuse(addr, timeout):
        raise TimeoutError("timed out")
    ok, msg = sup.preflight_db("postgres://u:p@h:31234/tsdb", connect=refuse)
    assert not ok and "31234" in msg and "only allow outbound" in msg

    ok, msg = sup.preflight_db("postgres://u:p@h:443/tsdb", connect=refuse)
    assert not ok and "only allow outbound" not in msg

    class Sock:
        def close(self):
            pass
    ok, msg = sup.preflight_db("postgres://u:p@h:31234/tsdb", connect=lambda a, timeout: Sock())
    assert ok and "reachable" in msg


def test_commands_api_on_7860_llm_loopback(tmp_path):
    gguf = tmp_path / "m.gguf"
    gguf.write_bytes(b"GGUF")
    c = sup.commands({"LLAMA_MODEL_PATH": str(gguf), "PYTHON": "py"})
    assert c["api"][:3] == ["py", "-m", "uvicorn"] and c["api"][c["api"].index("--port") + 1] == "7860"
    assert c["worker"] == ["py", "-m", "witness.worker"]
    assert c["llm"][c["llm"].index("--host") + 1] == "127.0.0.1"
    assert c["llm"][c["llm"].index("--port") + 1] == "8080"
    assert "llm" not in sup.commands({"LLAMA_MODEL_PATH": str(tmp_path / "missing.gguf")})
    assert "llm" not in sup.commands({"LLAMA_MODEL_PATH": str(gguf), "WITNESS_LOCAL_LLM": "off"})


class FakeProc:
    n = 0

    def __init__(self, cmd):
        FakeProc.n += 1
        self.pid, self.cmd, self.returncode, self.terminated = FakeProc.n, cmd, None, False

    def poll(self):
        return self.returncode

    def terminate(self):
        self.terminated, self.returncode = True, -15

    def wait(self, timeout=None):
        return self.returncode

    def kill(self):
        self.returncode = -9


def test_supervisor_restarts_with_backoff_and_stops():
    s = sup.Supervisor({"api": ["a"], "worker": ["w"]}, popen=FakeProc)
    s.start("api")
    s.start("worker")
    t0 = s.children["api"].started
    assert s.tick(t0 + 5) == []                     # all alive
    s.children["api"].proc.returncode = 1
    assert s.tick(t0 + 0.5) == []                   # backoff (1s) not elapsed
    assert s.tick(t0 + 1.5) == ["api"]
    a = s.children["api"]
    a.proc.returncode = 1
    assert s.backoff(a) == 2
    assert s.tick(a.started + 1) == [] and s.tick(a.started + 2) == ["api"]
    a.restarts = 10
    assert s.backoff(a) == 30                       # capped
    procs = [c.proc for c in s.children.values()]
    s.stop()
    assert all(p.terminated for p in procs)
    for p in procs:
        p.returncode = 1
    assert s.tick(10**9) == []                      # no restarts while stopping


def test_space_readme_front_matter():
    text = open(os.path.join(HF, "README.md")).read()
    m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    assert m, "README.md must start with YAML front matter"
    meta = yaml.safe_load(m.group(1))
    assert meta["sdk"] == "docker" and meta["app_port"] == 7860
    assert meta["title"]


def test_dockerfile_invariants():
    d = open(os.path.join(HF, "Dockerfile")).read()
    assert "useradd -m -u 1000 user" in d and "\nUSER 1000" in d
    assert "PORT=7860" in d and "EXPOSE 7860" in d and "/healthz" in d
    assert 'CMD ["python", "supervise.py"]' in d and "ENTRYPOINT []" in d
    for line in d.splitlines():                     # every COPY is chowned to the runtime user (HF guidance)
        if line.startswith("COPY "):
            assert "--chown=user" in line, line
    assert "TIGER_DB_URL" not in d and "TOKEN" not in d  # no secrets baked in


def test_make_space_assembles(tmp_path):
    out = tmp_path / "space"
    subprocess.run(["bash", os.path.join(HF, "make-space.sh"), str(out)], check=True, capture_output=True)
    for f in ("Dockerfile", "README.md", "supervise.py", "requirements.txt", "tigerkit.py", "tigerprod.py",
              "witness/api.py", "witness/worker.py", "sql/01_schema.sql", ".dockerignore"):
        assert (out / f).exists(), f
    assert not list(out.rglob("__pycache__")) and not (out / ".env").exists()


@pytest.mark.skipif(not shutil.which("node"), reason="node not installed")
def test_cloudflare_worker_node_tests():
    d = os.path.join(ROOT, "deploy", "oracle", "cloudflare-worker")
    r = subprocess.run(["node", "--test", "test/"], cwd=d, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stdout + r.stderr


def test_supervise_is_stdlib_only():
    src = open(os.path.join(HF, "supervise.py")).read()
    mods = set(re.findall(r"^(?:from|import) (\w+)", src, re.M))
    assert mods <= set(sys.stdlib_module_names), mods - set(sys.stdlib_module_names)
