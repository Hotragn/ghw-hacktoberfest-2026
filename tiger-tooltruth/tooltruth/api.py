"""FastAPI + dashboard.  uvicorn tooltruth.api:app --port 8101
Hardened: optional API key (TOOLTRUTH_API_KEY; required when TOOLTRUTH_ENV=prod), rate limiting,
bounded/validated inputs, JSON error envelopes with request ids, structured logs, health/readiness probes."""
from __future__ import annotations
import os, sys
from contextlib import asynccontextmanager
from datetime import timedelta
from fastapi import Depends, FastAPI, HTTPException, Path, Query
from fastapi.responses import FileResponse
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tigerkit import load_env, make_pool  # noqa: E402
from tigerprod import RateLimiter, enforce_prod_config, install_http_hardening, require_api_key_dependency, setup_logging  # noqa: E402

load_env()
setup_logging()
enforce_prod_config("TOOLTRUTH")
STATIC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static")
pool = None
NS = r"^[a-z][a-z0-9_\-]{0,31}$"
TOOL = r"^[a-z][a-z0-9_\-]{0,31}\.[a-z0-9_\-]{1,64}$"


@asynccontextmanager
async def lifespan(_):
    global pool
    pool = await make_pool("tooltruth", max_size=int(os.environ.get("TOOLTRUTH_DB_POOL", "5")))
    yield
    await pool.close()

app = FastAPI(title="ToolTruth", version="1.0.0", lifespan=lifespan,
              dependencies=[Depends(require_api_key_dependency("TOOLTRUTH_API_KEY"))])
install_http_hardening(app, "tooltruth", RateLimiter(int(os.environ.get("TOOLTRUTH_RATE_PER_MIN", "240")), 60))
Hours = Query(24, ge=1, le=24 * 30)


def rows(rs):
    return [dict(r) for r in rs]


@app.get("/")
async def index():
    return FileResponse(os.path.join(STATIC, "index.html"))


@app.get("/healthz")
async def healthz():
    return {"ok": True}


@app.get("/readyz")
async def readyz():
    try:
        await pool.fetchval("SELECT 1")
    except Exception:  # noqa: BLE001
        raise HTTPException(503, "database unavailable") from None
    return {"ok": True}


@app.get("/api/health")
async def health(hours: int = Hours):
    return rows(await pool.fetch("SELECT * FROM tool_health($1) ORDER BY error_rate DESC NULLS LAST", timedelta(hours=hours)))


@app.get("/api/suspects")
async def suspects(hours: int = Hours, ns: str | None = Query(None, pattern=NS),
                   max_distance: float = Query(0.05, gt=0, le=2)):
    return rows(await pool.fetch("SELECT * FROM behaving_like_known_bad($1,$2,$3)", timedelta(hours=hours), ns, max_distance))


@app.get("/api/new-destinations")
async def new_dest(hours: int = Query(12, ge=1, le=24 * 30)):
    return rows(await pool.fetch("SELECT * FROM new_destinations($1)", timedelta(hours=hours)))


@app.get("/api/orgs")
async def orgs(hours: int = Hours):
    return rows(await pool.fetch("SELECT * FROM org_spend($1)", timedelta(hours=hours)))


@app.get("/api/series/{tool}")
async def series(tool: str = Path(pattern=TOOL), hours: int = Query(48, ge=1, le=24 * 30)):
    r = await pool.fetch("""SELECT bucket, calls, error_rate, p95_latency_ms, avg_bytes_out, cost_per_success
                            FROM tool_hourly WHERE tool=$1 AND bucket > now() - $2::interval ORDER BY bucket""",
                         tool, timedelta(hours=hours))
    if not r:
        raise HTTPException(404, "unknown tool")
    return rows(r)


@app.get("/api/eth")
async def eth():
    return rows(await pool.fetch("SELECT * FROM eth_usd_1m ORDER BY bucket DESC LIMIT 60"))
