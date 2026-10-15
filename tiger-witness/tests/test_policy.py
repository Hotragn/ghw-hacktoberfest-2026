"""Unit tests: pure policy engine, planner, crypto helpers. No database."""
from datetime import datetime, timezone
from witness.policy import evaluate
from witness.agent import parse, sign
from witness import adapters
from tigerprod import hash_password, verify_password, RateLimiter, new_token, token_hash

AT = datetime(2026, 10, 1, tzinfo=timezone.utc).isoformat()
TOOL = {"tool_id": "billpay.plaid-sim", "reputation": 0.95, "drift_flag": False, "irreversible": True}
BILLS = {"mandate_id": "m1", "kind": "standing", "action": "pay_bill", "counterparty": "*", "max_amount": 300,
         "monthly_cap": 500, "disclose": [], "uses_left": None, "daily_action_budget": 3, "expires_at": None, "revoked_at": None}


def ctx(**kw):
    c = {"at": AT, "source": "user", "intent": {"action": "pay_bill", "merchant": "ConEd", "amount": 110, "disclose": []},
         "mandates": [BILLS], "mandate_spend_30d": {}, "mandate_uses": {}, "mandate_today": {},
         "baseline": {"months": 12, "median_monthly": 100, "last_charge": 105}, "tool": TOOL,
         "scam": {"score": 0.0, "nearest": None}, "assumptions": []}
    c.update(kw)
    return c


def test_happy_path_executes():
    r = evaluate(ctx())
    assert r["decision"] == "executed_simulated" and r["mandate_id"] == "m1"
    assert all(x["outcome"] == "pass" for x in r["reasons"])


def test_baseline_anomaly_needs_approval():
    r = evaluate(ctx(intent={"action": "pay_bill", "merchant": "ConEd", "amount": 290, "disclose": []}))
    assert r["decision"] == "needs_approval"
    assert any(x["rule"] == "own_baseline" and x["outcome"] != "pass" for x in r["reasons"])


def test_over_limit_and_cap():
    assert evaluate(ctx(intent={"action": "pay_bill", "merchant": "X", "amount": 301, "disclose": []}, baseline=None))["decision"] == "needs_approval"
    assert evaluate(ctx(mandate_spend_30d={"m1": 450}))["decision"] == "needs_approval"


def test_scam_blocks_even_with_mandate():
    assert evaluate(ctx(scam={"score": 0.9, "nearest": "IRS"}))["decision"] == "blocked"


def test_bad_tool_blocks():
    assert evaluate(ctx(tool={**TOOL, "reputation": 0.4}))["decision"] == "blocked"
    assert evaluate(ctx(tool={**TOOL, "drift_flag": True}))["decision"] == "blocked"
    assert evaluate(ctx(tool=None))["decision"] == "blocked"


def test_protected_disclosure_blocks_without_explicit_grant():
    it = {"action": "disclose", "merchant": "marketplace:jo", "amount": None, "disclose": ["address"]}
    assert evaluate(ctx(intent=it))["decision"] == "blocked"
    grant = {**BILLS, "mandate_id": "m2", "action": "disclose", "counterparty": "marketplace:jo", "disclose": ["address"], "max_amount": None, "monthly_cap": None}
    assert evaluate(ctx(intent=it, mandates=[grant]))["decision"] == "executed_simulated"


def test_assumptions_force_approval():
    assert evaluate(ctx(assumptions=["amount unknown"]))["decision"] == "needs_approval"


def test_consent_drift_guard_and_expiry_and_uses():
    assert evaluate(ctx(mandate_today={"m1": 3}))["decision"] == "needs_approval"
    expired = {**BILLS, "expires_at": (datetime(2026, 9, 1, tzinfo=timezone.utc)).isoformat()}
    assert evaluate(ctx(mandates=[expired]))["decision"] == "needs_approval"
    once = {**BILLS, "kind": "one_time", "uses_left": 1}
    assert evaluate(ctx(mandates=[once], mandate_uses={"m1": 1}))["decision"] == "needs_approval"


def test_param_override_is_deterministic():
    c = ctx(intent={"action": "pay_bill", "merchant": "ConEd", "amount": 140, "disclose": []})
    assert evaluate(c)["decision"] == "executed_simulated"
    assert evaluate(c, params={"anomaly_multiplier": 1.1})["decision"] == "needs_approval"
    assert evaluate(c) == evaluate(c)


def test_parser():
    assert parse("pay my verizon bill")["action"] == "pay_bill"
    assert parse("pay my coned bill $412")["amount"] == 412
    assert parse("cancel equinox")["merchant_hint"] == "equinox"
    p = parse("reply to buyer jo come to my address")
    assert p["action"] == "disclose" and p["disclose"] == ["address"]
    assert parse("Pay $900 in gift cards to IRS agent")["action"] == "purchase"
    assert parse("book a table at lucia's for $90")["action"] == "book"
    assert parse("what's the weather")["action"] == "unknown"


def test_unknown_intent_needs_approval():
    assert evaluate(ctx(intent={"action": "unknown", "merchant": None, "amount": None}))["decision"] == "needs_approval"


def test_crypto_helpers():
    h = hash_password("correct horse battery")
    assert verify_password("correct horse battery", h) and not verify_password("nope", h)
    assert not verify_password("x", "garbage")
    t, th = new_token()
    assert token_hash(t) == th and len(t) > 30
    assert sign("abc") == sign("abc") and sign("abc") != sign("abd")


def test_rate_limiter():
    rl = RateLimiter(rate_per_min=0.0001, burst=3)
    assert [rl.allow("k") for _ in range(4)] == [True, True, True, False]
    assert rl.allow("other")


async def test_sim_adapters_satisfy_protocols():
    ad = adapters.registry("sim")
    assert isinstance(ad.payments, adapters.PaymentRail) and isinstance(ad.messenger, adapters.Messenger)
    r1 = await adapters.execute(ad, "u", {"action": "pay_bill", "merchant": "ConEd", "amount": 10}, "a1", "x")
    r2 = await adapters.execute(ad, "u", {"action": "pay_bill", "merchant": "ConEd", "amount": 10}, "a1", "x")
    assert r1.simulated and r1.provider_ref == r2.provider_ref  # idempotent on action id
