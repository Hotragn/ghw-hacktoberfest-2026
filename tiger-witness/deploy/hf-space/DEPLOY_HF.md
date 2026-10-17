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
| `TIGER_DB_URL` | `postgres://witness_app:<APP_PW>@<svc>.<proj>.tsdb.cloud.timescale.com:<port>/tsdb?sslmode=require` |
| `WITNESS_SIGNING_KEY` | `openssl rand -base64 48` (≥32 chars, required in prod) |
| `GROQ_API_KEY` | from console.groq.com (router main tier) |
| `CLOUDFLARE_ACCOUNT_ID`, `CLOUDFLARE_API_TOKEN` | Workers AI (token with "Workers AI: Read") |
| `OPENROUTER_API_KEY` | openrouter.ai (free models) |
| `GEMINI_API_KEY` | optional. Only used if `WITNESS_GEMINI_OPT_IN=true` |
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_WEBHOOK_SECRET` | from @BotFather; the secret is `openssl rand -hex 32` |
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
```
The Worker acks Telegram/WhatsApp with a 200 within milliseconds and puts the request in the queue. The
consumer forwards the exact bytes (so the WhatsApp HMAC still verifies) and retries 5xx and timeouts with
backoff from 15 s to 5 min, up to 20 times. A Space waking up or rebuilding is covered. The origin dedupes
retries. A cron pings `/healthz` every 6 h. (Free CPU Basic Spaces sleep after 48 h of inactivity, and
"anyone visiting your Space will restart it". HF doesn't say whether API hits count as visits, so check
in the Space's status after a few days.) Without a queue binding, the Worker forwards synchronously and
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
