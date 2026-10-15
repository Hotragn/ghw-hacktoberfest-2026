"""Pure, deterministic policy engine. No I/O: every input is in `ctx`, so any past decision can be replayed
bit-for-bit, or re-run under a proposed policy ("what would have happened if...")."""
from __future__ import annotations
import fnmatch
from datetime import datetime

POLICY_VERSION = "2026.10.15-1"
DEFAULT_PARAMS = {
    "min_tool_reputation": 0.80,   # ToolTruth-style score floor
    "scam_block": 0.55,            # inbound-request scam score that blocks outright
    "anomaly_multiplier": 1.5,     # amount vs the user's own baseline for that merchant
    "protected_classes": ["address", "health", "financial"],
}
IRREVERSIBLE = {"pay_bill", "purchase", "book", "cancel_subscription", "disclose"}


def _parse(ts):
    return datetime.fromisoformat(ts) if isinstance(ts, str) else ts


def match_mandate(intent: dict, mandates: list[dict], at: str) -> dict | None:
    now = _parse(at)
    for m in mandates:
        if m["action"] != intent["action"] or m.get("revoked_at"):
            continue
        if m.get("expires_at") and _parse(m["expires_at"]) < now:
            continue
        if fnmatch.fnmatch((intent.get("merchant") or "").lower(), m["counterparty"].lower()):
            return m
    return None


def evaluate(ctx: dict, params: dict | None = None, mandates: list[dict] | None = None) -> dict:
    """Returns {decision, reasons:[{rule, outcome, detail}], mandate_id}. Rules run in a fixed order;
    every rule is recorded (pass or fail) so the receipt explains *why*, not just *what*."""
    p = {**DEFAULT_PARAMS, **(params or {})}
    mandates = ctx["mandates"] if mandates is None else mandates
    it, reasons, verdict = ctx["intent"], [], "executed_simulated"

    def rule(name, ok, detail, fail="needs_approval"):
        nonlocal verdict
        reasons.append({"rule": name, "outcome": "pass" if ok else fail, "detail": detail})
        if not ok and (fail == "blocked" or verdict != "blocked"):
            verdict = fail

    if it["action"] == "unknown":
        rule("understood", False, "could not map request to a supported action", "needs_approval")
        return {"decision": verdict, "reasons": reasons, "mandate_id": None}

    sc = ctx.get("scam") or {}
    rule("inbound_scam_check", (sc.get("score") or 0) < p["scam_block"],
         f"source={ctx.get('source')} score={sc.get('score', 0):.2f} nearest={sc.get('nearest', '-')}", "blocked")

    t = ctx.get("tool")
    rule("tool_reputation", bool(t) and t["reputation"] >= p["min_tool_reputation"] and not t["drift_flag"],
         f"{t['tool_id']} rep={t['reputation']:.2f} drift={t['drift_flag']}" if t else "no vetted tool", "blocked")

    m = match_mandate(it, mandates, ctx["at"])
    allowed = set(m["disclose"]) if m else set()
    leaked = [c for c in it.get("disclose", []) if c in p["protected_classes"] and c not in allowed]
    rule("data_disclosure", not leaked, f"would reveal {leaked}" if leaked else f"reveals {it.get('disclose', [])}", "blocked")

    rule("mandate", m is not None, f"matched {m['mandate_id']} ({m['kind']})" if m else
         f"no mandate covers {it['action']} @ {it.get('merchant')}")
    amt = float(it.get("amount") or 0)
    if m:
        if m.get("max_amount") is not None:
            rule("per_action_limit", amt <= float(m["max_amount"]), f"${amt:.2f} vs max ${float(m['max_amount']):.2f}")
        if m.get("monthly_cap") is not None:
            spent = float(ctx.get("mandate_spend_30d", {}).get(m["mandate_id"], 0))
            rule("rolling_30d_cap", spent + amt <= float(m["monthly_cap"]),
                 f"${spent:.2f} spent + ${amt:.2f} vs cap ${float(m['monthly_cap']):.2f}")
        if m.get("uses_left") is not None:
            used = int(ctx.get("mandate_uses", {}).get(m["mandate_id"], 0))
            rule("uses_left", used < int(m["uses_left"]), f"used {used} of {m['uses_left']}")
        if m["kind"] == "standing" and m.get("daily_action_budget"):
            today = int(ctx.get("mandate_today", {}).get(m["mandate_id"], 0))
            rule("consent_drift_guard", today < int(m["daily_action_budget"]),
                 f"{today} autonomous actions today vs budget {m['daily_action_budget']}")

    b = ctx.get("baseline") or {}
    ref = max(float(b.get("last_charge") or 0), float(b.get("median_monthly") or 0))
    if amt > 0 and ref > 0:
        rule("own_baseline", amt <= p["anomaly_multiplier"] * ref,
             f"${amt:.2f} vs your usual ${ref:.2f} ({b.get('months', 0)} months of history)")
    elif amt > 0 and it["action"] in IRREVERSIBLE:
        rule("own_baseline", m is not None and m["kind"] == "one_time", "no spending history with this merchant")

    asm = ctx.get("assumptions") or []
    rule("evidence_bound", not asm, "all facts cited from memory" if not asm else f"uncited assumptions: {asm}")
    return {"decision": verdict, "reasons": reasons, "mandate_id": m["mandate_id"] if m else None}
