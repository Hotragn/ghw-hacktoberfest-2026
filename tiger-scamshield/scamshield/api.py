"""FastAPI + dashboard with consent controls.  uvicorn scamshield.api:app --port 8102
Hardened: API key (SCAMSHIELD_API_KEY; required when SCAMSHIELD_ENV=prod), rate limiting, validated inputs,
JSON error envelopes with request ids, structured logs, health/readiness probes."""
from __future__ import annotations
import json, os, sys
from contextlib import asynccontextmanager
from datetime import timedelta
from fastapi import Depends, FastAPI, HTTPException, Path, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tigerkit import load_env, make_pool  # noqa: E402
from tigerprod import RateLimiter, enforce_prod_config, install_http_hardening, require_api_key_dependency, setup_logging  # noqa: E402

load_env()
setup_logging()
enforce_prod_config("SCAMSHIELD")
HID = Path(pattern=r"^hh-[0-9]{3,6}$")
Days = Query(7, ge=1, le=90)

STATIC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static")
pool = None


@asynccontextmanager
async def lifespan(_):
    global pool
    pool = await make_pool("scamshield")
    yield
    await pool.close()

app = FastAPI(title="ScamShield Home (simulated)", version="1.0.0", lifespan=lifespan,
              dependencies=[Depends(require_api_key_dependency("SCAMSHIELD_API_KEY"))])
install_http_hardening(app, "scamshield", RateLimiter(int(os.environ.get("SCAMSHIELD_RATE_PER_MIN", "240")), 60))


def rows(rs):
    out = []
    for r in rs:
        d = dict(r)
        for k, v in d.items():
            if isinstance(v, str) and k == "reasons":
                d[k] = json.loads(v)
        out.append(d)
    return out


class Actor(BaseModel):
    actor: str = Field(min_length=1, max_length=80)
    hours: int = Field(24, ge=1, le=24 * 30)


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


@app.get("/")
async def index():
    return FileResponse(os.path.join(STATIC, "index.html"))


@app.get("/api/households")
async def households():
    return rows(await pool.fetch("""SELECT h.household_id, h.display_name, h.consent_status, h.consent_scopes, h.paused_until,
             h.trusted_contact, (SELECT max(risk_score) FROM alerts a WHERE a.household_id=h.household_id
                                 AND a.ts > now()-interval '1 day') AS risk
             FROM households h ORDER BY 1"""))


@app.get("/api/households/{hid}/features")
async def features(hid: str = HID, days: int = Days):
    r = await pool.fetchrow("SELECT * FROM risk_features($1,$2)", hid, timedelta(days=days))
    return dict(r)


@app.get("/api/households/{hid}/storylines")
async def storylines(hid: str = HID, category: str | None = Query(None, pattern=r"^[a-z_\-]{1,40}$")):
    return rows(await pool.fetch("SELECT * FROM similar_storylines($1,$2,0.95,3)", hid, category))


@app.get("/api/fake-profit")
async def fake_profit(days: int = Days):
    return rows(await pool.fetch("SELECT * FROM fake_profit_screens($1) LIMIT 50", timedelta(days=days)))


@app.get("/api/alerts")
async def alerts():
    return rows(await pool.fetch("SELECT id, ts, household_id, risk_score, storyline, delivery, message FROM alerts ORDER BY ts DESC LIMIT 20"))


@app.get("/api/btc")
async def btc():
    return rows(await pool.fetch("SELECT * FROM btc_1m ORDER BY bucket DESC LIMIT 60"))


@app.get("/api/consent-log")
async def consent_log():
    return rows(await pool.fetch("SELECT * FROM consent_log ORDER BY ts DESC LIMIT 30"))


@app.post("/api/households/{hid}/pause")
async def pause(body: Actor, hid: str = HID):
    if not await pool.fetchval("SELECT 1 FROM households WHERE household_id=$1", hid):
        raise HTTPException(404, "unknown household")
    await pool.execute("SELECT pause_monitoring($1,$2,$3)", hid, body.actor, timedelta(hours=body.hours))
    return {"ok": True}


@app.post("/api/households/{hid}/revoke")
async def revoke(body: Actor, hid: str = HID):
    if not await pool.fetchval("SELECT 1 FROM households WHERE household_id=$1", hid):
        raise HTTPException(404, "unknown household")
    return {"result": await pool.fetchval("SELECT revoke_consent($1,$2)", hid, body.actor)}
