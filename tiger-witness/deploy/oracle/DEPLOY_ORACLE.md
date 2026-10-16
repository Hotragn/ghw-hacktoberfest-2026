# Deploy Witness on Oracle Cloud Always Free

You end up with one Ampere A1 VM (arm64, 2 OCPU / 12 GB, $0/month) that runs the whole stack:

| Service | Role |
|---|---|
| `caddy` | HTTPS for your domain (Let's Encrypt, auto-renew) |
| `api` | FastAPI app, web UI, chat webhooks |
| `worker` | durable-queue worker (channel messages, turns parked on exhausted quota, re-embedding) |
| `db` | TimescaleDB + pgvector (self-hosted on the VM) |
| `llm` | llama.cpp server with Qwen3-1.7B Q4_K_M, used for the light tier only |

Users never set anything up. All model keys are yours (one account per provider) and stay in `.env` on the VM.

> Oracle halved the Always Free A1 allowance on 2026-06-15, to **2 OCPU / 12 GB**. Don't create a 4 OCPU shape, it will bill.

## 0. What you need (about 45 minutes)
- [ ] An Oracle Cloud account. Signup needs **your** credit/debit card for identity verification; Always Free resources are not charged. Pick your home region carefully, you can't change it later. Pick one with A1 capacity (e.g. us-ashburn-1, us-phoenix-1, eu-frankfurt-1).
- [ ] A domain or subdomain you control (e.g. `witness.yourname.dev`). Any DNS provider works; Cloudflare DNS is free.
- [ ] The provider keys in step 4 (Groq is the important one).
- [ ] An SSH key pair. Create one with `ssh-keygen -t ed25519 -f ~/.ssh/oracle_witness`.

## 1. Create the network (VCN) and open ports 80 and 443
1. Console → **Networking → Virtual cloud networks → Start VCN Wizard → "Create VCN with Internet Connectivity"**. Keep the defaults and create it.
2. Open the VCN → **Security Lists → Default Security List → Add Ingress Rules**. Add two rules, both with source `0.0.0.0/0` and protocol TCP:
   - destination port **80** (Let's Encrypt HTTP challenge plus redirect);
   - destination port **443** (HTTPS). Also add **UDP 443** if you want HTTP/3.
   Port 22 is already open. Leave everything else closed: Postgres and llama.cpp are never exposed.

## 2. Create the VM
Go to Console → **Compute → Instances → Create instance**.
- **Image:** Canonical **Ubuntu 24.04** (aarch64).
- **Shape:** Ampere → **VM.Standard.A1.Flex**, with **2 OCPU, 12 GB** memory. The "Always Free-eligible" tag must show.
- **Networking:** the VCN from step 1, the public subnet, and "Assign a public IPv4 address".
- **SSH keys:** paste `~/.ssh/oracle_witness.pub`.
- **Boot volume:** 100 GB. Always Free includes 200 GB of block storage in total.
- **Show advanced options → Management → Cloud-init script:** paste the contents of `deploy/oracle/cloud-init.yaml`.
- Create it. If you get "Out of capacity", retry later or in another availability domain. A1 capacity is often tight.

Cloud-init then does the following (about 5–10 minutes after boot):
- installs Docker;
- opens ports 80 and 443 in the **OS firewall** (Oracle's Ubuntu images ship an iptables REJECT rule, so the security list alone is not enough);
- adds 4 GB of swap;
- clones this repo to `/opt/witness`;
- downloads the model (about 1.1 GB);
- enables the `witness-compose` systemd unit.

## 3. Point DNS at the VM
Copy the instance's **public IP**. At your DNS provider, create an `A` record `witness.yourname.dev → <public IP>`. If you use Cloudflare, set it to **DNS only** (grey cloud) for now so Caddy can get its certificate.

## 4. Get the provider keys (once, for the whole service)
| Secret | Where | Needed? |
|---|---|---|
| `GROQ_API_KEY` | console.groq.com → API Keys | **Yes.** Primary pool: gpt-oss-120b, qwen3.8-27b, gpt-oss-20b |
| `CLOUDFLARE_ACCOUNT_ID` and `CLOUDFLARE_API_TOKEN` | dash.cloudflare.com → AI → Workers AI → "Use REST API" (token with Workers AI permission) | Recommended. About 10K neurons/day |
| `OPENROUTER_API_KEY` | openrouter.ai/keys | Optional free-model tail (50 RPD) |
| `GEMINI_API_KEY` plus `WITNESS_GEMINI_OPT_IN=true` | aistudio.google.com | Optional. The free tier trains on inputs, so Witness only sends **non-personal** turns there. Disclose this in your privacy policy |
| `NVIDIA_API_KEY` | build.nvidia.com | Leave **off** in production. The NIM ToS is prototyping only |
| `TELEGRAM_BOT_TOKEN` and `TELEGRAM_WEBHOOK_SECRET` | @BotFather; `openssl rand -hex 24` | If you use Telegram |
| `WHATSAPP_*` | Meta developer app | If you use WhatsApp |
| `STRIPE_*` | Stripe dashboard | Only for real payments (otherwise simulated) |

Use one account per provider. Never create extra accounts to multiply free quota.

## 5. Configure and start
```bash
ssh -i ~/.ssh/oracle_witness ubuntu@<public IP>
cloud-init status --wait                       # wait until "status: done"
cd /opt/witness/tiger-witness/deploy/oracle
cp .env.example .env && chmod 600 .env
sed -i "s|^POSTGRES_PASSWORD=.*|POSTGRES_PASSWORD=$(openssl rand -hex 24)|" .env
sed -i "s|^WITNESS_SIGNING_KEY=.*|WITNESS_SIGNING_KEY=$(openssl rand -hex 32)|" .env
nano .env                                      # set WITNESS_DOMAIN, ACME_EMAIL, PUBLIC_URL/RP_ID/ORIGIN, provider keys
sudo systemctl start witness-compose           # = docker compose --env-file .env up -d --build
docker compose ps                              # all services "running"/"healthy"; migrate "exited (0)"
curl -fsS https://$(grep ^WITNESS_DOMAIN .env | cut -d= -f2)/healthz
```
The first build on arm64 takes about 10–15 minutes, mostly pip installs and baking in the embedding model.

## 6. Connect channels
- **Telegram:**
  ```bash
  curl "https://api.telegram.org/bot$TELEGRAM_BOT_TOKEN/setWebhook" \
    -d url=https://<domain>/channels/telegram/webhook -d secret_token=$TELEGRAM_WEBHOOK_SECRET
  ```
- **WhatsApp:** in the Meta app, set the webhook to `https://<domain>/channels/whatsapp/webhook`, with the verify token `WHATSAPP_VERIFY_TOKEN`.
- Open `https://<domain>/app`, register, add a **passkey**, then go to Channels → link code and send `link <CODE>` to the bot.

### Optional: Cloudflare Worker ingress
`cloudflare-worker/` holds a 40-line Worker that checks the Telegram secret at the edge and forwards webhooks to the VM. If the VM is down it returns 503, so the providers retry later.
1. Run `cd cloudflare-worker && npx wrangler deploy && npx wrangler secret put TELEGRAM_WEBHOOK_SECRET`.
2. Set `ORIGIN` in `wrangler.toml` to your domain.
3. Point the Telegram webhook at `https://witness-ingress.<you>.workers.dev/channels/telegram/webhook`.

## 7. Operate
| Task | Command |
|---|---|
| Logs | `docker compose logs -f api worker llm` |
| Update | `cd /opt/witness && git pull && cd tiger-witness/deploy/oracle && docker compose up -d --build` |
| Back up the DB (nightly cron) | `docker compose exec -T db pg_dump -U postgres -Fc tsdb > ~/witness-$(date +%F).dump` |
| Check the queue | `docker compose exec db psql -U postgres tsdb -c "select queue,status,count(*) from witness.jobs group by 1,2"` |
| Model sanity check | `docker compose exec api python -c "import urllib.request;print(urllib.request.urlopen('http://llm:8080/health').read())"` |

**Idle reclaim:** Oracle may reclaim Always Free instances that stay under 20% CPU for 7 days. A live bot rarely stays that idle. If yours does, upgrading the account to Pay-As-You-Go (still $0 if you stay within Always Free) removes the reclaim policy.

## Firewall summary
There are two layers, and **both** must allow 80 and 443:
1. **The VCN security list** (step 1). This is Oracle's cloud firewall.
2. **The VM's iptables** (cloud-init does this). To do it by hand:
   ```bash
   sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 80 -j ACCEPT
   sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 443 -j ACCEPT
   sudo netfilter-persistent save
   ```
   Don't use `ufw` alongside Oracle's iptables rules: they conflict.

Docker publishes only 80 and 443 (Caddy). The API binds to 127.0.0.1, and Postgres and llama.cpp are reachable only on the compose network.

## Capacity you can expect
These figures are from `/workspace/witness-research/ZERO_FRICTION.md`:
- about **20–35 daily active users** at 20 messages/day on the free pool, with caching and routing on;
- the local Qwen3-1.7B handles light/trivial turns at about 1–2K short calls/day on 2 OCPU (see `docs/ROUTER.md` for measured tok/s);
- when every provider is out, users get **"Saved, I'll reply by ~HH:MM"** and the worker answers after the reset.
