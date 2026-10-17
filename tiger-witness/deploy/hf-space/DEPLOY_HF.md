# Deploy Witness to a Hugging Face Space (+ Tiger Cloud + Cloudflare Worker)

Suggested Space name: **`witness`**, so the URL is `https://<hf-username>-witness.hf.space`.

## 0. Read this first: two blockers checked on 2026-10-17

1. **Docker Spaces need a paid HF plan to create.** The CPU Basic hardware (2 vCPU, 16 GB RAM, 50 GB
   disk) costs nothing per hour. But HF's docs now say *"Gradio and Docker Spaces run on compute and require
   a paid plan to create: PRO for personal accounts"*. Only Static Spaces (and up to 2 ZeroGPU Gradio Spaces)
   are free. So this deploy needs **HF PRO** (see https://huggingface.co/pricing).
2. **Outbound ports.** HF's docs say *"you can make requests through the standard HTTP and HTTPS ports (80 and
   443) along with port 8080. Any requests going to other ports will be blocked."* Tiger Cloud services
   listen on a per-service high port (e.g. `:3xxxx`), not 5432 or 443. **The Space will probably not reach
   Tiger Cloud.** `supervise.py` tests the connection at boot and logs `ERROR: cannot reach database ... only
   allow outbound ports [80, 443, 8080]` when it fails. Do not get around this with Cloudflare Tunnel or a
   proxy: HF's Content Policy lists *"Using tools like Cloudflare Tunnel, TOR, proxies ... to bypass
   restrictions"* as platform abuse. If the preflight fails, the honest options are a host that allows the
   port (Fly.io, Render, Koyeb, a VPS) or a database reachable on 443.

Steps 1 to 6 below assume you accept both points. Do step 4 (preflight) before anything else.

## 1. Accounts
- Hugging Face: sign up at https://huggingface.co/join, then subscribe to PRO (Settings → Billing).
- Create a write token for git pushes: https://huggingface.co/settings/tokens.
- Tiger Cloud: you already have it. Free services allow connections from any IP until you attach an IP allow
  list (Console → Security → IP Allow List). HF egress IPs are not fixed, so leave the service unrestricted
  and use a strong password plus the least-privilege `witness_app` role.

## 2. Tiger Cloud migrations (run once from your laptop, as tsdbadmin)
```bash
cd tiger-witness
export ADMIN_URI='postgres://tsdbadmin:<pw>@<svc>.<proj>.tsdb.cloud.timescale.com:<port>/tsdb?sslmode=require'
TIGER_DB_URL="$ADMIN_URI" python -m witness.setup_db
APP_PW=$(openssl rand -base64 32); echo "$APP_PW"     # keep this for TIGER_DB_URL below
psql "$ADMIN_URI" -v app_password="'$APP_PW'" -f sql/roles.sql
```
Run the same `setup_db` again after every release that adds `sql/NN_*.sql`. The Space never migrates.

## 3. Create the Space
- https://huggingface.co/new-space → name `witness`, SDK **Docker** (blank template), hardware **CPU Basic**,
  visibility **Public** (webhooks must reach it; HF can't hide a Private Space's app behind a public URL).
  The source becomes public too, which is fine: it holds no secrets.
- Assemble and push:
```bash
git clone https://huggingface.co/spaces/<hf-username>/witness ~/witness-space
tiger-witness/deploy/hf-space/make-space.sh ~/witness-space
cd ~/witness-space && git add -A && git commit -m "deploy witness" && git push   # user: hf username, pw: token
```
The first build takes about 10 minutes (pip install, embedding model, 1.1 GB GGUF baked in).

## 4. Secrets and variables (Space → Settings → Variables and secrets)
**Secrets** (private):

| name | value |
| --- | --- |
| `TIGER_DB_URL` | `postgres://witness_app:<APP_PW>@<svc>.<proj>.tsdb.cloud.timescale.com:<port>/tsdb?sslmode=verify-full` (prod refuses anything weaker) |
| `WITNESS_EDGE_SECRET` | `openssl rand -hex 32`. The **same value** goes into the Worker. Webhooks without a valid Worker HMAC get 401 |
| `WITNESS_SIGNING_KEY` | `openssl rand -base64 48` (≥32 chars, required in prod) |
| `GROQ_API_KEY` | from console.groq.com (router main tier) |
| `CLOUDFLARE_ACCOUNT_ID`, `CLOUDFLARE_API_TOKEN` | Workers AI (token with "Workers AI: Read") |
| `OPENROUTER_API_KEY` | openrouter.ai (free models) |
| `GEMINI_API_KEY` | optional. Only used if `WITNESS_GEMINI_OPT_IN=true` |
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_WEBHOOK_SECRET` | from @BotFather; the secret is `openssl rand -hex 32` |
| `IMESSAGE_WEBHOOK_SECRET` | BlueBubbles relay shared secret (optional) |
| `WHATSAPP_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID`, `WHATSAPP_APP_SECRET`, `WHATSAPP_VERIFY_TOKEN` | Meta app (optional) |

**Variables** (public):

| name | value |
| --- | --- |
| `WITNESS_ENV` | `prod` |
| `WITNESS_COOKIE_SECURE` | `true` |
| `WITNESS_PUBLIC_URL` | `https://<hf-username>-witness.hf.space` |
| `WITNESS_ORIGIN` | same as above (passkeys) |
| `WITNESS_RP_ID` | `<hf-username>-witness.hf.space` |
| `WITNESS_ALLOW_REGISTRATION` | `false` once you've registered yourself |
| `WITNESS_TZ` | `America/New_York` |
| `WITNESS_DB_POOL` | `4` (the api and worker each open a pool; Tiger free has few connections) |
| `WITNESS_LOCAL_LLM` | `off` to skip llama.cpp (saves about 1.6 GB RAM and some CPU) |
| `WITNESS_DB_POOL_MIN` | `2` (warm TLS connections kept open by the API) |
| `WITNESS_SENDER_RATE_PER_MIN` / `WITNESS_SENDER_BURST` | `20` / `10` per chat id or phone number |
| `WITNESS_CORS_ORIGINS` | leave **unset** (same-origin only). `*` is ignored |

Saving secrets restarts the Space. Then check **Logs**: you want
`[supervise] OK: database ... reachable` and `started api/worker/llm`. Then
`curl https://<hf-username>-witness.hf.space/healthz` should return `{"ok":true}` and `/readyz` should
return `{"ok":true}` (that one proves the DB connection).

## 5. Cloudflare Worker ingress (ack fast, queue while the Space wakes)
```bash
cd tiger-witness/deploy/oracle/cloudflare-worker
# edit wrangler.toml: ORIGIN = "https://<hf-username>-witness.hf.space"
npx wrangler login
npx wrangler queues create witness-webhooks
npx wrangler deploy
npx wrangler secret put TELEGRAM_WEBHOOK_SECRET      # same value as the Space secret
npx wrangler secret put WITNESS_EDGE_SECRET          # same value as the Space secret
npx wrangler secret put WHATSAPP_APP_SECRET          # if using WhatsApp (verified at the edge AND in the app)
npx wrangler secret put IMESSAGE_WEBHOOK_SECRET      # if using the BlueBubbles relay
```
Unset secrets make the Worker reject that channel (fails closed).
The Worker acks Telegram/WhatsApp with a 200 within milliseconds and puts the request in the queue. The
consumer forwards the exact bytes (so the WhatsApp HMAC still verifies) and retries 5xx and timeouts with
backoff from 15 s to 5 min, up to 20 times. A Space waking up or rebuilding is covered. The origin dedupes
retries. A cron sends `GET /health` every 10 min (144 tiny requests a day) so the Space stays warm and the
first message doesn't hit a cold start. (Free CPU Basic Spaces sleep after 48 h of inactivity, and
"anyone visiting your Space will restart it". HF doesn't say whether API hits count as visits, so check
the Space's status after a few days.) On ToS: HF's Terms and Content Policy don't mention keep-alive pings.
The policy does forbid using tools "to bypass restrictions", and the 48 h sleep is a free-tier resource
control. A slow ping is low-impact, but it is a grey area. If you'd rather not risk it, remove the
`[triggers]` block: the queue still delivers every message after a wake, just slower on the first one. Without a queue binding, the Worker forwards synchronously and
returns 503 so the provider retries.

## 6. Webhooks
- Telegram:
```bash
curl "https://api.telegram.org/bot$TELEGRAM_BOT_TOKEN/setWebhook" \
  -d url=https://witness-ingress.<cf-subdomain>.workers.dev/channels/telegram/webhook \
  -d secret_token=$TELEGRAM_WEBHOOK_SECRET
```
- WhatsApp (Meta app → WhatsApp → Configuration): callback URL
  `https://witness-ingress.<cf-subdomain>.workers.dev/channels/whatsapp/webhook`, verify token
  `WHATSAPP_VERIFY_TOKEN`, subscribe to `messages`. The verify GET passes through to the Space, which must be
  awake for that one request.

## Limits to know (verified 2026-10-17)
| item | value | source |
| --- | --- | --- |
| CPU Basic | 2 vCPU, 16 GB RAM, 50 GB disk, free per hour | https://huggingface.co/docs/hub/spaces-gpus |
| disk | not persistent, wiped on restart (Storage Bucket optional) | https://huggingface.co/docs/hub/spaces-sdks-docker#data-persistence |
| sleep | after 48 h inactive; a visit restarts it; custom sleep needs paid hardware | https://huggingface.co/docs/hub/spaces-gpus#set-a-custom-sleep-time |
| Docker SDK | `sdk: docker`, `app_port`, runs as uid 1000 | https://huggingface.co/docs/hub/spaces-sdks-docker |
| create Docker Space | needs PRO/Team/Enterprise | https://huggingface.co/docs/hub/spaces-overview |
| egress | ports 80, 443, 8080 only | https://huggingface.co/docs/hub/spaces-overview#networking |
| URL | `https://<owner>-<space>.hf.space` (`SPACE_HOST`) | https://huggingface.co/docs/hub/spaces-overview |
| secrets | runtime env vars; buildtime via `--mount=type=secret` | https://huggingface.co/docs/hub/spaces-sdks-docker |
| policy | no bypass proxies/tunnels, no spam/bulk, no unauthorized bot APIs | https://huggingface.co/content-policy |

## Latency design
| hop | what makes it fast |
| --- | --- |
| provider → Worker | Edge verification (Telegram secret, WhatsApp HMAC, BlueBubbles token), enqueue, then **200 in under 1 ms of Worker CPU**. Telegram/WhatsApp never wait for the Space |
| Worker → Space | Queue consumer forwards at once. The Space is kept warm by the 10-min `/health` cron, so no cold start |
| Space → DB | asyncpg pool with `min_size` warm, long-lived TLS (verify-full) connections. The handshake is paid once per connection, not per query |
| Space → LLM | light turns go **Groq first** (`openai/gpt-oss-20b`), then Workers AI, OpenRouter, Gemini (opt-in), local llama.cpp last |
| prompt caching | exact + semantic reply caches in the router, a byte-stable system prompt (`STREAM_SYSTEM`) so provider-side prefix caching applies, and llama.cpp `--cache-reuse 256` |
| local model | GGUF baked into the image, mmapped and loaded at container start (`supervise.py` logs `llm model loaded (mmap) in Xs`) |
| web chat | `POST /api/v2/chat/stream` (SSE) streams light first-turn, non-personal answers token by token. Anything with tools or personal data goes through the normal agent (taint/consent/passkey gating unchanged) and arrives as one `final` event |

### Measured (2026-10-17, this repo's box: 8 vCPU Xeon, local Postgres 17 + TimescaleDB, no network hops)
`python scripts/bench_latency.py` and `node deploy/oracle/cloudflare-worker/bench.mjs`:

| path | p50 | p95 | n |
| --- | --- | --- | --- |
| Worker: Telegram verify + enqueue + ack (in-process) | 0.027 ms | 0.054 ms | 2000 |
| Worker: WhatsApp HMAC verify + enqueue + ack (in-process) | 0.086 ms | 0.262 ms | 2000 |
| App: edge HMAC sign + verify | 0.009 ms | 0.012 ms | 2000 |
| App: `GET /health` (ASGI) | 0.53 ms | 0.70 ms | 300 |
| App: edge-signed Telegram webhook → verify both signatures → durable enqueue in Postgres | 2.12 ms | 2.85 ms | 300 |
| App: `/api/v2/chat/stream` time to first byte, mocked Groq (app overhead only) | 2.58 ms | 3.35 ms | 200 |
| DB: `SELECT 1` on a pooled connection | 0.13 ms | 0.18 ms | 300 |
| DB: `SELECT 1` on a fresh connection (no TLS, localhost) | 7.82 ms | 9.05 ms | 100 |

Not measured here, because the box has no Groq key, no Space and no route to Tiger: real Groq TTFT, the
HF/Cloudflare network hops, and the TLS handshake to Tiger us-east-1. A fresh remote TLS connection costs
several round trips on top of the 7.8 ms above, which is exactly what the warm pool avoids. Run
`bench_latency.py` again inside the Space (Settings → Dev mode, PRO) for real numbers.

## Threat model
**Assets:** your messages and memories (Tiger), channel tokens, LLM API keys, the signing key, and the
ability to make Witness act (send, pay, disclose).

| threat | mitigation |
| --- | --- |
| Forged webhook to the Worker | Telegram `X-Telegram-Bot-Api-Secret-Token`, WhatsApp `X-Hub-Signature-256` (HMAC over the raw body), BlueBubbles shared secret: all checked at the edge with constant-time compares and **again in the app**. 1 MB body cap |
| Bypassing the Worker by hitting `*.hf.space` directly | Webhook routes require the Worker→Space HMAC (`WITNESS_EDGE_SECRET`): ts + nonce + method + path + sha256(body) |
| Replay of a captured request | ±60 s timestamp window + single-use nonce cache. Provider message ids are queue dedupe keys, so redelivery is a no-op |
| Flooding / cost exhaustion | Cloudflare in front. Per-IP token bucket in the app, per-sender (chat id/phone) bucket on webhooks, per-user daily LLM budgets plus a new-user reserve in the router. Note: behind HF's proxy the "client IP" comes from `X-Forwarded-For`, which a client can spoof, so per-sender and per-user limits are the real controls |
| DB MITM / credential sniffing | `sslmode=verify-full` (CA + hostname, TLS ≥ 1.2). The app refuses to start in prod without it. Least-privilege `witness_app` role; migrations run only as tsdbadmin from your laptop |
| Secret leakage | Secrets only in HF Space secrets and Cloudflare Worker secrets, never in git, the image, or build args. `make-space.sh` never copies `.env`. Note: Space *variables* are public; never put secrets there |
| Supply chain | Base image pinned by digest, GGUF pinned to a repo commit and checked against sha256, Python deps hash-locked (`pip --require-hashes`), runs as non-root uid 1000 with `--no-install-recommends` |
| XSS / clickjacking / CSRF-style cross-origin use | CSP (`default-src 'self'`, `connect-src 'self'`, `frame-ancestors 'none'`, `object-src 'none'`), HSTS, COOP/CORP, nosniff, `no-store` on API responses. No CORS unless explicitly allow-listed. Remaining gap: inline scripts/handlers need `'unsafe-inline'`; moving them to static files would let CSP drop it |
| Prompt injection making the agent act | Unchanged: taint/consent firewall, approvals, passkey step-up for protected actions. Streaming only covers tool-free, non-personal light turns |
| Public Space source | Contains no secrets. Anyone can read the code, which is fine because security does not depend on hiding it |
| HF platform risk | Docker needs PRO; outbound is limited to ports 80/443/8080 (Tiger's port is likely blocked); the disk is ephemeral. All state lives in Tiger |
