"""Zero-friction model router: server-side pooled free providers, no BYOK, no user setup.

Order of resolution for every model call (cheapest first):
  1. deterministic commands (help, ping, status, thanks...) -> no LLM at all
  2. exact-match cache, then semantic cache: ONLY for non-personal, tool-free questions
  3. per-user daily budget + new-user reserve (fairness before spending pooled quota)
  4. pooled providers by tier, skipping any that are rate-limited (learned from 429 / x-ratelimit-* headers and
     local RPM/RPD/TPD counters) or whose circuit breaker is open
  5. local llama.cpp (Qwen3-1.7B) for light tasks only
  6. nothing left -> QuotaExhausted(retry_at) computed from the earliest provider reset; callers queue the turn
     durably (witness.jobs) and tell the user "Saved, I'll reply by ~HH:MM".

Tiers: "light" (chit-chat, short non-tool answers), "main" (agent turns with tools), "strong" (anything that can
move money: only strong models, never local / OpenRouter free / Gemini free).
Privacy: providers flagged personal_ok=False (Gemini free tier trains on inputs) never see personal turns and are
only enabled with WITNESS_GEMINI_OPT_IN=true. ToS: one account per provider; NVIDIA build is prototyping-only per
its FAQ, so it is off unless WITNESS_NVIDIA_ALLOW_PROTOTYPE=true (dev/staging)."""
from __future__ import annotations
import asyncio
import contextvars
import hashlib
import json
import logging
import math
import os
import re
import time
from collections import OrderedDict, deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Awaitable, Callable
import httpx
from witness.llm import Completion, ToolCall

log = logging.getLogger("witness.router")
DAY = 86400.0

# Per-call context set by the agent loop (user id, risk). A contextvar keeps the Provider protocol unchanged.
CTX: contextvars.ContextVar[dict | None] = contextvars.ContextVar("witness_llm_ctx", default=None)


class QuotaExhausted(Exception):
    """No provider can serve this call now. retry_at is a unix timestamp (earliest reset); reason is for logs."""

    def __init__(self, retry_at: float, reason: str = "providers"):
        super().__init__(f"quota exhausted ({reason}); retry at {retry_at:.0f}")
        self.retry_at, self.reason = retry_at, reason


# ----------------------------------------------------------------------------------------------- configuration
@dataclass
class Route:
    provider: str
    model: str
    tiers: frozenset
    rpm: int | None = None
    rpd: int | None = None
    tpm: int | None = None
    tpd: int | None = None

    @property
    def key(self) -> str:
        return f"{self.provider}/{self.model}"


@dataclass
class ProviderSpec:
    name: str
    base_url: str
    api_key: str
    routes: list[Route]
    personal_ok: bool = True
    local: bool = False
    timeout: float = 45.0
    extra_headers: dict = field(default_factory=dict)


def _t(*names):
    return frozenset(names)


def pool_from_env(env: dict | None = None) -> list[ProviderSpec]:
    """Build the provider pool from server-side env. Missing keys simply drop that provider."""
    e = os.environ if env is None else env
    g = e.get
    out: list[ProviderSpec] = []
    if g("GROQ_API_KEY"):  # console.groq.com free: per model 30 RPM, 1K RPD, 8K TPM, 200K TPD
        lim = dict(rpm=30, rpd=1000, tpm=8000, tpd=200_000)
        out.append(ProviderSpec("groq", g("GROQ_BASE_URL", "https://api.groq.com/openai/v1"), g("GROQ_API_KEY"), [
            Route("groq", g("GROQ_MODEL_STRONG", "openai/gpt-oss-120b"), _t("strong", "main"), **lim),
            Route("groq", g("GROQ_MODEL_MAIN", "qwen/qwen3.8-27b"), _t("strong", "main"), **lim),
            Route("groq", g("GROQ_MODEL_LIGHT", "openai/gpt-oss-20b"), _t("main", "light"), **lim)]))
    if g("CLOUDFLARE_API_TOKEN") and g("CLOUDFLARE_ACCOUNT_ID"):  # 10K neurons/day
        out.append(ProviderSpec("cloudflare", g("CLOUDFLARE_BASE_URL",
                   f"https://api.cloudflare.com/client/v4/accounts/{g('CLOUDFLARE_ACCOUNT_ID')}/ai/v1"),
                   g("CLOUDFLARE_API_TOKEN"), [
            Route("cloudflare", g("CLOUDFLARE_MODEL_MAIN", "@cf/meta/llama-3.3-70b-instruct-fp8-fast"),
                  _t("main"), rpm=300, tpd=int(g("CLOUDFLARE_TPD", "200000"))),
            Route("cloudflare", g("CLOUDFLARE_MODEL_LIGHT", "@cf/meta/llama-3.1-8b-instruct-fast"),
                  _t("light"), rpm=300, tpd=int(g("CLOUDFLARE_TPD", "200000")))]))
    if g("OPENROUTER_API_KEY"):  # :free models, 20 RPM / 50 RPD per account (1K RPD after a one-time $10 top-up)
        rpd = int(g("OPENROUTER_RPD", "50"))
        models = [m.strip() for m in g("OPENROUTER_FREE_MODELS", "openai/gpt-oss-120b:free,qwen/qwen3-30b-a3b:free").split(",") if m.strip()]
        out.append(ProviderSpec("openrouter", g("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"), g("OPENROUTER_API_KEY"),
                   [Route("openrouter", m, _t("main", "light"), rpm=20, rpd=rpd) for m in models],
                   extra_headers={"HTTP-Referer": g("WITNESS_PUBLIC_URL", "https://witness.local"), "X-Title": "Witness"}))
    if g("NVIDIA_API_KEY") and g("WITNESS_NVIDIA_ALLOW_PROTOTYPE", "false").lower() == "true":
        out.append(ProviderSpec("nvidia", g("NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1"), g("NVIDIA_API_KEY"), [
            Route("nvidia", g("NVIDIA_MODEL", "openai/gpt-oss-120b"), _t("strong", "main"), rpm=40)]))
    if g("GEMINI_API_KEY") and g("WITNESS_GEMINI_OPT_IN", "false").lower() == "true":
        out.append(ProviderSpec("gemini", g("GEMINI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta/openai"),
                   g("GEMINI_API_KEY"), [Route("gemini", g("GEMINI_MODEL", "gemini-2.5-flash-lite"), _t("light", "main"),
                                               rpm=15, rpd=int(g("GEMINI_RPD", "500")))], personal_ok=False))
    if g("WITNESS_LLM_BASE_URL") and g("WITNESS_LLM_API_KEY"):  # operator-owned custom endpoint (still server-side)
        out.append(ProviderSpec("custom", g("WITNESS_LLM_BASE_URL"), g("WITNESS_LLM_API_KEY"), [
            Route("custom", g("WITNESS_LLM_MODEL", "gpt-4o-mini"), _t("strong", "main", "light"))]))
    if g("WITNESS_LOCAL_LLM_URL"):  # llama.cpp server on the same box: light tier only (CPU is ~10 tok/s)
        out.append(ProviderSpec("local", g("WITNESS_LOCAL_LLM_URL"), g("WITNESS_LOCAL_LLM_KEY", "local"), [
            Route("local", g("WITNESS_LOCAL_LLM_MODEL", "qwen3-1.7b"), _t("light"))], local=True, timeout=120.0))
    return out


# ----------------------------------------------------------------------------------------- rate + breaker state
def _next_utc_midnight(now: float) -> float:
    d = datetime.fromtimestamp(now, timezone.utc).date() + timedelta(days=1)
    return datetime(d.year, d.month, d.day, tzinfo=timezone.utc).timestamp()


def _day(now: float) -> str:
    return datetime.fromtimestamp(now, timezone.utc).strftime("%Y-%m-%d")


_DUR = re.compile(r"(?:(\d+(?:\.\d+)?)h)?(?:(\d+(?:\.\d+)?)m(?!s))?(?:(\d+(?:\.\d+)?)s)?(?:(\d+(?:\.\d+)?)ms)?$")


def parse_reset(value: str | None, now: float) -> float | None:
    """Reset hint -> absolute unix time. Handles Groq durations ('2m59.56s', '7.66s', '120ms'), plain seconds,
    unix seconds and unix milliseconds (OpenRouter X-RateLimit-Reset)."""
    if not value:
        return None
    v = value.strip()
    try:
        x = float(v)
        if x > 1e12:
            return x / 1000.0
        if x > 1e9:
            return x
        return now + x
    except ValueError:
        pass
    m = _DUR.match(v)
    if m and any(m.groups()):
        h, mi, s, ms = (float(x) if x else 0.0 for x in m.groups())
        return now + h * 3600 + mi * 60 + s + ms / 1000.0
    return None


class RouteState:
    """What we know about one provider/model: local counters + server-reported limits + circuit breaker."""

    def __init__(self, route: Route, breaker_threshold: int = 3, breaker_base_s: float = 30.0):
        self.route = route
        self.blocked_until = 0.0
        self.minute: deque = deque()          # (ts, tokens)
        self.day, self.day_req, self.day_tok = "", 0, 0
        self.failures, self.open_until = 0, 0.0
        self.threshold, self.base = breaker_threshold, breaker_base_s

    def _roll(self, now: float):
        if self.day != _day(now):
            self.day, self.day_req, self.day_tok = _day(now), 0, 0
        while self.minute and self.minute[0][0] <= now - 60:
            self.minute.popleft()

    def available_at(self, now: float, est_tokens: int = 0) -> float:
        """Earliest time this route can take a call of est_tokens (== now when available)."""
        self._roll(now)
        r, t = self.route, now
        t = max(t, self.blocked_until, self.open_until)
        if (r.rpd and self.day_req >= r.rpd) or (r.tpd and self.day_tok + est_tokens > r.tpd):
            t = max(t, _next_utc_midnight(now))
        if r.rpm and len(self.minute) >= r.rpm:
            t = max(t, self.minute[0][0] + 60)
        if r.tpm and self.minute and sum(x[1] for x in self.minute) + est_tokens > r.tpm:
            t = max(t, self.minute[0][0] + 60)
        return t

    def record(self, now: float, tokens: int):
        self._roll(now)
        self.minute.append((now, tokens))
        self.day_req += 1
        self.day_tok += tokens

    def observe_headers(self, headers, now: float, status: int):
        """Learn limits from the provider. 429 always blocks until the reported reset (or 60s)."""
        h = {k.lower(): v for k, v in headers.items()}
        reset = None
        for rem_k, reset_k in (("x-ratelimit-remaining-requests", "x-ratelimit-reset-requests"),
                               ("x-ratelimit-remaining-tokens", "x-ratelimit-reset-tokens"),
                               ("x-ratelimit-remaining", "x-ratelimit-reset")):
            rem = h.get(rem_k)
            if rem is not None:
                try:
                    if float(rem) <= 0:
                        rt = parse_reset(h.get(reset_k), now)
                        reset = max(reset or 0, rt or now + 60)
                except ValueError:
                    pass
        if status == 429:
            ra = parse_reset(h.get("retry-after"), now)
            reset = max(reset or 0, ra or 0, *(x for x in (parse_reset(h.get(k), now) for k in
                        ("x-ratelimit-reset-requests", "x-ratelimit-reset-tokens", "x-ratelimit-reset")) if x)) or now + 60
        if reset:
            self.blocked_until = max(self.blocked_until, reset)

    def ok(self):
        self.failures, self.open_until = 0, 0.0

    def fail(self, now: float):
        self.failures += 1
        if self.failures >= self.threshold:  # open; each further failure doubles the cooldown (max 15 min)
            self.open_until = now + min(900.0, self.base * 2 ** (self.failures - self.threshold))

    @property
    def breaker(self) -> str:
        return "open" if self.open_until > time.time() else ("half-open" if self.failures >= self.threshold else "closed")


# --------------------------------------------------------------------------------------------- budgets (fairness)
class MemoryBudgetStore:
    def __init__(self):
        self.usage: dict[tuple[str, str], list[int]] = {}
        self.first: dict[str, float] = {}

    async def get(self, subject: str, day: str) -> tuple[int, int]:
        r = self.usage.get((subject, day), [0, 0])
        return r[0], r[1]

    async def add(self, subject: str, day: str, req: int, tok: int) -> None:
        r = self.usage.setdefault((subject, day), [0, 0])
        r[0] += req
        r[1] += tok

    async def first_seen(self, user: str, now: float) -> float:
        return self.first.setdefault(user, now)


class PgBudgetStore:
    """Durable counters in witness.llm_usage / witness.llm_users (survive restarts, shared by api + workers)."""

    def __init__(self, pool):
        self.pool = pool

    async def get(self, subject, day):
        r = await self.pool.fetchrow("SELECT requests, tokens FROM witness.llm_usage WHERE subject=$1 AND day=$2::text::date", subject, day)
        return (r["requests"], r["tokens"]) if r else (0, 0)

    async def add(self, subject, day, req, tok):
        await self.pool.execute("""INSERT INTO witness.llm_usage (subject, day, requests, tokens) VALUES ($1,$2::text::date,$3,$4)
            ON CONFLICT (subject, day) DO UPDATE SET requests = llm_usage.requests + EXCLUDED.requests,
            tokens = llm_usage.tokens + EXCLUDED.tokens""", subject, day, req, tok)

    async def first_seen(self, user, now):
        v = await self.pool.fetchval("""INSERT INTO witness.llm_users (user_id, first_seen) VALUES ($1, to_timestamp($2))
            ON CONFLICT (user_id) DO UPDATE SET user_id = EXCLUDED.user_id RETURNING extract(epoch FROM first_seen)""", user, now)
        return float(v)


@dataclass
class BudgetPolicy:
    user_daily_tokens: int = 60_000
    user_daily_requests: int = 80
    new_user_days: float = 3.0
    new_user_reserve: float = 0.15   # fraction of pooled daily tokens held back for users seen < new_user_days ago
    pool_daily_tokens: int | None = None  # defaults to the sum of route TPDs

    @classmethod
    def from_env(cls):
        g = os.environ.get
        return cls(int(g("WITNESS_USER_DAILY_TOKENS", "60000")), int(g("WITNESS_USER_DAILY_REQUESTS", "80")),
                   float(g("WITNESS_NEW_USER_DAYS", "3")), float(g("WITNESS_NEW_USER_RESERVE", "0.15")),
                   int(g("WITNESS_POOL_DAILY_TOKENS")) if g("WITNESS_POOL_DAILY_TOKENS") else None)


# ---------------------------------------------------------------------------------------------- deterministic path
_HELP = ("I'm Witness. Just tell me what you need: \"remember ...\", \"pay my electric bill\", \"what's on my calendar\", "
         "\"read https://...\". Anything that spends money asks for your passkey first.")
_COMMANDS: list[tuple[re.Pattern, Callable[[str], str]]] = [
    (re.compile(r"^/?(help|start|commands|what can you do\??)$", re.I), lambda _: _HELP),
    (re.compile(r"^/?ping$", re.I), lambda _: "pong"),
    (re.compile(r"^(thanks|thank you|thx|ty)[.! ]*$", re.I), lambda _: "Anytime."),
    (re.compile(r"^(hi|hello|hey|yo)[.! ]*$", re.I), lambda _: "Hi! What can I do for you?"),
    (re.compile(r"^/?(status)$", re.I), lambda _: "Witness is up. Your messages are processed in order."),
    (re.compile(r"^what(?:'s| is) the (?:utc )?(?:time|date)(?: now)?\??$", re.I),
     lambda _: datetime.now(timezone.utc).strftime("It's %Y-%m-%d %H:%M UTC.")),
]


def deterministic(text: str) -> str | None:
    t = (text or "").strip()
    for rx, fn in _COMMANDS:
        if rx.match(t):
            return fn(t)
    return None


_PERSONAL = re.compile(r"\b(i|i'm|im|me|my|mine|myself|we|our|us|remember|forget|pay|paid|bill|buy|order|email|mail|"
                       r"calendar|meeting|file|note|address|account|password|bank|card|phone|send|book|remind)\b", re.I)
_MONEY = re.compile(r"\$\s?\d|\b\d+(?:\.\d+)?\s?(?:usd|dollars|eur|€|£)\b|\b(pay|purchase|buy|order|wire|transfer|refund|checkout)\b", re.I)
_SPEND_TOOLS = {"pay"}


def is_personal(messages: list[dict]) -> bool:
    """Conservative: anything mentioning the user, tools, or carrying memories counts as personal (never cached,
    never sent to providers that train on inputs)."""
    for m in messages:
        if m.get("role") in ("tool",) or m.get("tool_calls"):
            return True
        if m.get("role") == "system" and "\n" in (m.get("content") or "") and (m["content"].rsplit("\n", 1)[-1].strip()):
            return True  # runtime.SYSTEM appends retrieved memories after the last newline
        if m.get("role") == "user" and _PERSONAL.search(m.get("content") or ""):
            return True
    return False


def tier_for(messages: list[dict], tools: list[dict], ctx: dict) -> str:
    names = {t.get("name") for t in tools or []}
    text = " ".join(m.get("content") or "" for m in messages if m.get("role") == "user")
    called = {tc.get("function", {}).get("name") for m in messages for tc in (m.get("tool_calls") or [])}
    if ctx.get("high_risk") or (called & _SPEND_TOOLS) or ((names & _SPEND_TOOLS) and _MONEY.search(text)):
        return "strong"
    if any(m.get("role") == "tool" for m in messages):
        return "main"
    last = next((m.get("content") or "" for m in reversed(messages) if m.get("role") == "user"), "")
    if len(last) <= 160 and not _PERSONAL.search(last) and "http" not in last:
        return "light"
    return "main"


# ------------------------------------------------------------------------------------------------------- caches
def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", "", (s or "").lower())).strip()


class ExactCache:
    def __init__(self, max_items: int = 5000, ttl_s: float = 6 * 3600):
        self.data: OrderedDict = OrderedDict()
        self.max, self.ttl = max_items, ttl_s

    @staticmethod
    def key(text: str, lang: str) -> str:
        return hashlib.sha256(f"{lang}|{_norm(text)}".encode()).hexdigest()

    def get(self, k: str, now: float) -> str | None:
        v = self.data.get(k)
        if not v or v[1] < now:
            self.data.pop(k, None)
            return None
        self.data.move_to_end(k)
        return v[0]

    def put(self, k: str, val: str, now: float):
        self.data[k] = (val, now + self.ttl)
        self.data.move_to_end(k)
        while len(self.data) > self.max:
            self.data.popitem(last=False)


class SemanticCache:
    """Cosine >= threshold over embeddings of non-personal questions. Linear scan is fine at a few thousand items."""

    def __init__(self, embed: Callable[[list[str]], Awaitable[list[list[float]]]], threshold: float = 0.95,
                 max_items: int = 2000, ttl_s: float = 6 * 3600):
        self.embed, self.th, self.max, self.ttl = embed, threshold, max_items, ttl_s
        self.items: deque = deque()

    @staticmethod
    def _cos(a, b):
        num = sum(x * y for x, y in zip(a, b))
        den = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
        return num / den if den else 0.0

    async def get(self, text: str, lang: str, now: float):
        v = (await self.embed([text]))[0]
        best, hit = 0.0, None
        for vec, l2, val, exp in self.items:
            if exp >= now and l2 == lang:
                c = self._cos(v, vec)
                if c > best:
                    best, hit = c, val
        return (hit if best >= self.th else None), v

    def put(self, vec, lang: str, val: str, now: float):
        self.items.append((vec, lang, val, now + self.ttl))
        while len(self.items) > self.max:
            self.items.popleft()


# -------------------------------------------------------------------------------------------------------- router
def _est_tokens(messages, tools) -> int:
    return (len(json.dumps(messages, default=str)) + len(json.dumps(tools or []))) // 4 + 256


class Router:
    name = "router"

    def __init__(self, pool: list[ProviderSpec], budgets=None, policy: BudgetPolicy | None = None,
                 embed=None, transport=None, clock: Callable[[], float] = time.time, local_concurrency: int = 1):
        self.specs = {p.name: p for p in pool}
        self.states = {r.key: RouteState(r) for p in pool for r in p.routes}
        self.budgets = budgets or MemoryBudgetStore()
        self.policy = policy or BudgetPolicy()
        self.exact = ExactCache()
        self.semantic = SemanticCache(embed) if embed else None
        self.clock = clock
        self.clients = {p.name: httpx.AsyncClient(timeout=p.timeout, transport=transport) for p in pool}
        self.local_sem = asyncio.Semaphore(local_concurrency)
        self.stats = {"deterministic": 0, "exact_hit": 0, "semantic_hit": 0, "calls": 0, "exhausted": 0}

    # ---- selection
    def candidates(self, tier: str, personal: bool) -> list[tuple[ProviderSpec, Route]]:
        order = {"strong": ["strong"], "main": ["main", "strong"], "light": ["light", "main"]}[tier]
        out, seen = [], set()
        for want in order:
            for p in self.specs.values():
                if personal and not p.personal_ok:
                    continue
                if tier == "strong" and (p.local or p.name in ("openrouter", "gemini")):
                    continue  # money moves only through strong, logged-out-of-training models
                if p.local and tier != "light":
                    continue
                for r in p.routes:
                    if want in r.tiers and r.key not in seen:
                        seen.add(r.key)
                        out.append((p, r))
        # local is the last resort for light work
        return sorted(out, key=lambda pr: pr[0].local)

    def pool_capacity(self) -> int:
        if self.policy.pool_daily_tokens:
            return self.policy.pool_daily_tokens
        return sum(s.route.tpd or 0 for s in self.states.values() if not self.specs[s.route.provider].local)

    async def _check_budget(self, user: str | None, now: float):
        if not user:
            return
        day, p = _day(now), self.policy
        req, tok = await self.budgets.get(f"user:{user}", day)
        if req >= p.user_daily_requests or tok >= p.user_daily_tokens:
            raise QuotaExhausted(_next_utc_midnight(now), "user_budget")
        cap = self.pool_capacity()
        if cap and p.new_user_reserve > 0:
            _, used = await self.budgets.get("pool", day)
            first = await self.budgets.first_seen(user, now)
            is_new = (now - first) < p.new_user_days * DAY
            if not is_new and used >= cap * (1 - p.new_user_reserve):
                raise QuotaExhausted(_next_utc_midnight(now), "new_user_reserve")

    # ---- call
    async def _call(self, p: ProviderSpec, r: Route, messages, tools) -> tuple[Completion, int, httpx.Response]:
        body = {"model": r.model, "messages": messages, "temperature": 0.2}
        if tools:
            body["tools"] = [{"type": "function", "function": t} for t in tools]
            body["tool_choice"] = "auto"
        headers = {"Authorization": f"Bearer {p.api_key}", **p.extra_headers}
        resp = await self.clients[p.name].post(f"{p.base_url.rstrip('/')}/chat/completions", json=body, headers=headers)
        if resp.status_code >= 400:
            return None, 0, resp
        data = resp.json()
        msg = data["choices"][0]["message"]
        calls = []
        for tc in msg.get("tool_calls") or []:
            try:
                args = json.loads(tc["function"].get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {"_raw": tc["function"].get("arguments")}
            calls.append(ToolCall(tc.get("id") or f"call_{len(calls)}", tc["function"]["name"],
                                  args if isinstance(args, dict) else {"value": args}))
        content = msg.get("content")
        if content and "<think>" in content:  # Qwen3 thinking traces never reach users
            content = re.sub(r"<think>.*?</think>\s*", "", content, flags=re.S).strip()
        used = int((data.get("usage") or {}).get("total_tokens") or 0)
        return Completion(content, calls), used, resp

    async def complete(self, messages: list[dict], tools: list[dict], lang: str) -> Completion:
        ctx = CTX.get() or {}
        now = self.clock()
        last = messages[-1] if messages else {}
        first_turn = last.get("role") == "user" and not any(m.get("role") in ("assistant", "tool") for m in messages)
        user_text = (last.get("content") or "") if last.get("role") == "user" else ""
        if first_turn:
            d = deterministic(user_text)
            if d:
                self.stats["deterministic"] += 1
                return Completion(d)
        personal = ctx.get("personal", False) or is_personal(messages)
        cacheable = first_turn and not personal
        vec = None
        if cacheable:
            k = ExactCache.key(user_text, lang)
            hit = self.exact.get(k, now)
            if hit is not None:
                self.stats["exact_hit"] += 1
                return Completion(hit)
            if self.semantic:
                try:
                    hit, vec = await self.semantic.get(user_text, lang, now)
                except Exception as e:  # noqa: BLE001 - the cache must never break a turn
                    log.warning("semantic cache lookup failed: %s", e)
                    hit = None
                if hit is not None:
                    self.stats["semantic_hit"] += 1
                    return Completion(hit)
        user = ctx.get("user")
        await self._check_budget(user, now)
        tier = tier_for(messages, tools, ctx)
        est = _est_tokens(messages, tools)
        cands = self.candidates(tier, personal)
        if not cands:
            self.stats["exhausted"] += 1
            raise QuotaExhausted(now + 3600, f"no_provider_for_{tier}")
        for p, r in cands:
            st = self.states[r.key]
            if st.available_at(now, est) > now:
                continue
            try:
                if p.local:
                    async with self.local_sem:
                        comp, used, resp = await self._call(p, r, messages, tools)
                else:
                    comp, used, resp = await self._call(p, r, messages, tools)
            except (httpx.HTTPError, KeyError, ValueError, IndexError) as e:
                st.fail(self.clock())
                log.warning("provider %s failed: %s: %s", r.key, type(e).__name__, e)
                continue
            now = self.clock()
            st.observe_headers(resp.headers, now, resp.status_code)
            if comp is None:
                if resp.status_code == 429:
                    log.info("provider %s rate-limited until %.0f", r.key, st.blocked_until)
                else:
                    st.fail(now)
                    log.warning("provider %s HTTP %s", r.key, resp.status_code)
                continue
            st.ok()
            used = used or est
            st.record(now, used)
            self.stats["calls"] += 1
            day = _day(now)
            await self.budgets.add("pool", day, 1, used)
            await self.budgets.add(f"prov:{r.key}", day, 1, used)
            if user:
                await self.budgets.add(f"user:{user}", day, 1, used)
            if cacheable and comp.content and not comp.tool_calls:
                self.exact.put(ExactCache.key(user_text, lang), comp.content, now)
                if self.semantic and vec is not None:
                    self.semantic.put(vec, lang, comp.content, now)
            log.info("routed tier=%s via %s tokens=%s", tier, r.key, used)
            return comp
        self.stats["exhausted"] += 1
        retry = min(self.states[r.key].available_at(self.clock(), est) for _, r in cands)
        raise QuotaExhausted(max(retry, self.clock() + 5), f"providers_{tier}")

    # ---- streaming (light, first-turn, non-personal, tool-free turns only)
    def streamable(self, messages: list[dict], ctx: dict | None = None) -> bool:
        ctx = ctx or {}
        return (bool(messages) and messages[-1].get("role") == "user"
                and not any(m.get("role") in ("assistant", "tool") for m in messages)
                and not (ctx.get("personal") or is_personal(messages))
                and tier_for(messages, [], ctx) == "light")

    async def _stream_call(self, p: ProviderSpec, r: Route, messages):
        body = {"model": r.model, "messages": messages, "temperature": 0.2, "stream": True,
                "stream_options": {"include_usage": True}}
        headers = {"Authorization": f"Bearer {p.api_key}", **p.extra_headers}
        async with self.clients[p.name].stream("POST", f"{p.base_url.rstrip('/')}/chat/completions",
                                               json=body, headers=headers) as resp:
            if resp.status_code >= 400:
                await resp.aread()
                yield resp, None, 0
                return
            async for line in resp.aiter_lines():
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                try:
                    j = json.loads(data)
                except json.JSONDecodeError:
                    continue
                used = int((j.get("usage") or {}).get("total_tokens") or 0)
                delta = ((j.get("choices") or [{}])[0].get("delta") or {}).get("content") if j.get("choices") else None
                yield resp, delta, used

    async def stream(self, messages: list[dict], lang: str = "en"):
        """Yield text deltas for a light turn. Falls over to the next route only before the first token, so the
        user never sees two half-answers. Deterministic and cache hits are yielded whole (zero model latency).
        Qwen3 <think> traces are suppressed. Raises QuotaExhausted like complete()."""
        ctx = CTX.get() or {}
        now = self.clock()
        user_text = messages[-1].get("content") or ""
        d = deterministic(user_text)
        if d:
            self.stats["deterministic"] += 1
            yield d
            return
        k = ExactCache.key(user_text, lang)
        hit = self.exact.get(k, now)
        if hit is not None:
            self.stats["exact_hit"] += 1
            yield hit
            return
        user = ctx.get("user")
        await self._check_budget(user, now)
        est = _est_tokens(messages, [])
        cands = self.candidates("light", False)
        for p, r in cands:
            st = self.states[r.key]
            if st.available_at(now, est) > now:
                continue
            parts, used, started, in_think = [], 0, False, False
            try:
                async for resp, delta, u in self._stream_call(p, r, messages):
                    used = u or used
                    if delta is None and not started and resp.status_code >= 400:
                        st.observe_headers(resp.headers, self.clock(), resp.status_code)
                        if resp.status_code != 429:
                            st.fail(self.clock())
                        break
                    if not delta:
                        continue
                    if "<think>" in delta:
                        in_think = True
                    if in_think:
                        if "</think>" in delta:
                            in_think, delta = False, delta.split("</think>", 1)[1].lstrip()
                        else:
                            continue
                    if delta:
                        started = True
                        parts.append(delta)
                        yield delta
            except (httpx.HTTPError, ValueError) as e:
                st.fail(self.clock())
                log.warning("stream %s failed: %s", r.key, type(e).__name__)
                if started:
                    return
                continue
            if not started:
                continue
            now = self.clock()
            st.ok()
            used = used or est
            st.record(now, used)
            self.stats["calls"] += 1
            day = _day(now)
            await self.budgets.add("pool", day, 1, used)
            await self.budgets.add(f"prov:{r.key}", day, 1, used)
            if user:
                await self.budgets.add(f"user:{user}", day, 1, used)
            self.exact.put(k, "".join(parts), now)
            log.info("streamed tier=light via %s tokens=%s", r.key, used)
            return
        self.stats["exhausted"] += 1
        raise QuotaExhausted(self.clock() + 60, "providers_light_stream")

    def health(self) -> dict:
        now = self.clock()
        return {k: {"available_in_s": max(0, round(s.available_at(now) - now)), "day_requests": s.day_req,
                    "day_tokens": s.day_tok, "breaker": s.breaker} for k, s in self.states.items()} | {"_stats": self.stats}

    async def aclose(self):
        for c in self.clients.values():
            await c.aclose()


def from_env(pool=None, transport=None) -> Router | None:
    specs = pool_from_env()
    if not specs:
        return None
    embed = None
    if os.environ.get("WITNESS_SEMANTIC_CACHE", "true").lower() == "true":
        try:
            from witness import embeddings
            e = embeddings.get()
            embed = e.embed
        except Exception:  # noqa: BLE001
            embed = None
    return Router(specs, PgBudgetStore(pool) if pool is not None else MemoryBudgetStore(), BudgetPolicy.from_env(),
                  embed=embed, transport=transport)


def eta_text(retry_at: float, tz: str | None = None) -> str:
    """'Saved, I'll reply by ~HH:MM TZ.' in the operator-configured zone (WITNESS_TZ, default UTC)."""
    from zoneinfo import ZoneInfo
    z = ZoneInfo(tz or os.environ.get("WITNESS_TZ", "UTC"))
    dt = datetime.fromtimestamp(math.ceil(retry_at / 60) * 60, z)
    return f"Saved, I'll reply by ~{dt:%H:%M} {dt.tzname()}."
