"""Integration boundary. The agent core only talks to these Protocols; providers plug in behind them.
Today every implementation is SIMULATED: it records what it *would* do and returns a fake reference.
To go live, implement the Protocol (e.g. PlaidBillPay, AP2Checkout, TwilioMessenger) and register it in `registry()`.
A live adapter must be idempotent on `idempotency_key` (= action_id) so retries never double-pay."""
from __future__ import annotations
import hashlib
import json
from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class ExecResult:
    ok: bool
    provider_ref: str
    simulated: bool
    detail: dict


@runtime_checkable
class PaymentRail(Protocol):
    name: str
    async def pay(self, *, user_id: str, merchant: str, amount: float, idempotency_key: str, memo: str) -> ExecResult: ...


@runtime_checkable
class SubscriptionManager(Protocol):
    name: str
    async def cancel(self, *, user_id: str, merchant: str, idempotency_key: str) -> ExecResult: ...


@runtime_checkable
class Booker(Protocol):
    name: str
    async def book(self, *, user_id: str, venue: str, amount: float | None, details: str, idempotency_key: str) -> ExecResult: ...


@runtime_checkable
class Messenger(Protocol):
    """Outbound replies on the user's own channel (SMS/WhatsApp/iMessage/Slack)."""
    name: str
    async def send(self, *, user_id: str, to: str, body: str, idempotency_key: str) -> ExecResult: ...


@runtime_checkable
class ToolReputationFeed(Protocol):
    """Source of tool scores, e.g. a ToolTruth deployment (`tooltruth.tool_health`)."""
    async def scores(self) -> dict[str, tuple[float, bool]]: ...


class _Sim:
    def _ref(self, *parts) -> str:
        return "sim_" + hashlib.sha256(json.dumps(parts, default=str).encode()).hexdigest()[:20]


class SimPaymentRail(_Sim):
    name = "sim-payments"
    async def pay(self, *, user_id, merchant, amount, idempotency_key, memo):
        return ExecResult(True, self._ref(user_id, merchant, amount, idempotency_key), True,
                          {"merchant": merchant, "amount": amount, "memo": memo, "note": "SIMULATED - no money moved"})


class SimSubscriptionManager(_Sim):
    name = "sim-subscriptions"
    async def cancel(self, *, user_id, merchant, idempotency_key):
        return ExecResult(True, self._ref(user_id, merchant, idempotency_key), True,
                          {"merchant": merchant, "note": "SIMULATED - nothing cancelled"})


class SimBooker(_Sim):
    name = "sim-booking"
    async def book(self, *, user_id, venue, amount, details, idempotency_key):
        return ExecResult(True, self._ref(user_id, venue, idempotency_key), True,
                          {"venue": venue, "amount": amount, "details": details, "note": "SIMULATED - no booking made"})


class SimMessenger(_Sim):
    name = "sim-messenger"
    async def send(self, *, user_id, to, body, idempotency_key):
        return ExecResult(True, self._ref(user_id, to, idempotency_key), True,
                          {"to": to, "chars": len(body), "note": "SIMULATED - nothing sent"})


@dataclass
class Adapters:
    payments: PaymentRail
    subscriptions: SubscriptionManager
    booking: Booker
    messenger: Messenger


def registry(mode: str = "sim") -> Adapters:
    if mode == "sim":
        return Adapters(SimPaymentRail(), SimSubscriptionManager(), SimBooker(), SimMessenger())
    raise SystemExit(f"adapter mode {mode!r} not installed; implement the Protocols in witness/adapters.py")


async def execute(ad: Adapters, user_id: str, intent: dict, action_id: str, request: str) -> ExecResult | None:
    a, m, amt = intent["action"], intent.get("merchant") or "", intent.get("amount")
    if a in ("pay_bill", "purchase"):
        return await ad.payments.pay(user_id=user_id, merchant=m, amount=float(amt or 0), idempotency_key=action_id, memo=a)
    if a == "cancel_subscription":
        return await ad.subscriptions.cancel(user_id=user_id, merchant=m, idempotency_key=action_id)
    if a == "book":
        return await ad.booking.book(user_id=user_id, venue=m, amount=amt, details=intent.get("item") or "", idempotency_key=action_id)
    if a in ("reply", "disclose"):
        return await ad.messenger.send(user_id=user_id, to=m, body=request, idempotency_key=action_id)
    return None
