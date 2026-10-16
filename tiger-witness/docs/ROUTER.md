# Zero-friction model router

Code: `witness/router.py`, `witness/deferral.py`. Tests: `tests/test_router.py`. Deploy: `deploy/oracle/DEPLOY_ORACLE.md`.

Users never bring a key and never configure anything. Witness owns **one account per provider** (ToS-compliant pooling across *different* providers) and the router spends that pooled free quota as carefully as it can.

## How it works
Every model call resolves in this order. Each step is cheaper than the next.

| # | Step | LLM? | Notes |
|---|---|---|---|
| 1 | Deterministic commands: `help`, `/start`, `ping`, `status`, `thanks`, `hi`, `what time is it` | no | First turn only |
| 2 | Exact-match cache (normalized text + language, 6 h TTL) | no | **Non-personal, tool-free first turns only** |
| 3 | Semantic cache (cosine ≥ 0.95 on the configured embedder) | no | Same restriction. Personal memory answers are never cached |
| 4 | Per-user daily budget (`WITNESS_USER_DAILY_TOKENS` / `_REQUESTS`) and a **new-user reserve** (the last 15% of pooled daily tokens go only to users first seen less than 3 days ago) | no | Counters live in Postgres `witness.llm_usage` and are shared by the API and workers |
| 5 | Pooled providers by tier, skipping a route when any of these hold: it was rate-limited (429 `retry-after`, `x-ratelimit-remaining-*` = 0 with `x-ratelimit-reset-*`), it is at its local RPM/TPM/RPD/TPD counters, or its circuit breaker is open | yes | Breaker opens after 3 consecutive failures for 30 s, doubling to a 15 min cap. One success closes it |
| 6 | Local llama.cpp Qwen3-1.7B, **light tier only** | yes (local) | Last resort for trivial replies |
| 7 | Everything exhausted: `QuotaExhausted(retry_at)` with the earliest reset across candidates. The turn is parked in the durable Postgres queue (`deferred`, SKIP LOCKED) and the user gets **"Saved, I'll reply by ~HH:MM TZ."** | — | See "When everything is exhausted" below |

### Tiers
- **light:** short, non-personal, tool-free turns. Routes, in order: groq gpt-oss-20b, Cloudflare 8B, OpenRouter `:free`, Gemini Flash-Lite (opt-in, non-personal), then local Qwen3-1.7B.
- **main:** agent turns with tools or tool results. Routes: groq qwen3.8-27b / gpt-oss-120b / gpt-oss-20b, Cloudflare Llama-3.3-70B, OpenRouter `:free`.
- **strong:** anything that can move money (a `pay` tool is available and the text mentions money, a `pay` call is in the transcript, or a parked `pay` approval is being resumed). Routes go **only** to strong models: groq gpt-oss-120b / qwen3.8-27b, plus NVIDIA if explicitly allowed. They never go to local, OpenRouter free or Gemini free. If no strong route is free, the turn is queued rather than downgraded. The passkey requirement for high-risk approvals (`witness/passkeys.py`) is unchanged.

### Privacy and ToS
- `is_personal()` is deliberately conservative. A turn counts as personal if any of these hold:
  - it mentions the user ("my", "I", "remember", "pay", "email"…);
  - it carries retrieved memories in the system prompt;
  - it has tool calls or tool results.

  Personal turns are never cached and never sent to `personal_ok=False` providers.
- **Gemini** free tier trains on inputs, so it is `personal_ok=False` and is only enabled with `WITNESS_GEMINI_OPT_IN=true`.
- **NVIDIA build** (NIM) is prototyping-only under its ToS, so it is enabled only with `WITNESS_NVIDIA_ALLOW_PROTOTYPE=true`. Keep that off in production.
- Never run multiple accounts at one provider.

### When everything is exhausted
- **Web** (`POST /api/v2/chat`) returns `{"status":"deferred","reply":"Saved, I'll reply by ~HH:MM TZ.","retry_at":…}`. The finished task later appears in `/api/v2/tasks`.
- **Channels** (Telegram, WhatsApp, iMessage) send the Saved message through the channel. The worker's `deferred` handler re-runs the turn after the reset and replies in the chat.
- **Fair drain:** a user's k-th parked turn gets `run_after = reset + k × WITNESS_DEFER_STAGGER_S` (20 s by default). Workers claim in `run_after` order, so one heavy user can't starve others after a reset.
- **Still exhausted at drain time:** the handler raises `jobs.Defer(new_reset)`, which re-parks the job **without consuming a retry attempt**. Real errors still use the normal backoff and dead-letter path.
- **Webhook retries** are de-duplicated by a hash of user, channel, text and message id.

## Configuration
Every secret is listed in `deploy/oracle/.env.example`. The router turns on automatically when any pool key is present (`GROQ_API_KEY`, `CLOUDFLARE_*`, `OPENROUTER_API_KEY`, `WITNESS_LOCAL_LLM_URL`, …). Set `WITNESS_ROUTER=off` to force the old single-endpoint mode. With no keys at all, the offline planner runs, as in tests.

Model IDs and limits are overridable via `GROQ_MODEL_*`, `CLOUDFLARE_MODEL_*`, `OPENROUTER_FREE_MODELS`, `GEMINI_MODEL` and `NVIDIA_MODEL`. The default limits come from the Oct 2026 free tiers:
- **Groq:** 30 RPM / 1K RPD / 8K TPM / 200K TPD per model;
- **OpenRouter:** 20 RPM / 50 RPD;
- **Gemini Flash-Lite:** 15 RPM / 500 RPD.

The server's own headers always override these defaults.

## Local CPU benchmark (reference)
- **Model:** Qwen3-1.7B Q4_K_M (unsloth GGUF, 1.03 GiB), via llama.cpp (llama-cpp-python 0.3.36). Thinking is disabled with an empty `<think></think>` block. Prompt: 305 tokens. Generation: 128 tokens, greedy.
- **Box:** 8 vCPU Intel Xeon (x86-64), 16 GB RAM. It was **heavily shared** during the run: load average 13–19 and under 1 GB of RAM free. Treat these numbers as a pessimistic floor, not a clean measurement.
- **Run date:** 2026-10-16.

| Threads | Prompt processing | Generation |
|---|---|---|
| 2 | 47.7 – 50.4 tok/s | 1.9 tok/s |
| 4 | 50.2 tok/s | 1.7 tok/s |

**What this means for Oracle A1 (2 OCPU Ampere, 12 GB, dedicated):**
- Prefill of about 50 tok/s matches the research estimate (40–80 tok/s).
- Generation on this contended box is well below the estimated 8–12 tok/s. That is because the box is memory-bandwidth starved. On a dedicated A1 with nothing else decoding, expect several times this figure. Re-measure on the VM with:
  ```bash
  docker compose exec llm /app/llama-bench -m /models/Qwen3-1.7B-Q4_K_M.gguf -t 2 -p 300 -n 128
  ```
- Either way, the local model is right only for routing labels, 1–2 sentence replies and "queued" notices. That is why it is light-tier-only and last in line.
