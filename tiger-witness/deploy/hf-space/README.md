---
title: Witness
emoji: 🐯
colorFrom: yellow
colorTo: gray
sdk: docker
app_port: 7860
pinned: false
license: apache-2.0
short_description: Personal AI agent with consent firewall (Tiger Cloud)
---

# Witness on Hugging Face Spaces

One Docker container:

| process | port | role |
| --- | --- | --- |
| `uvicorn witness.api:app` | 7860 (public) | web app, API, chat webhooks, `GET /healthz` (liveness), `GET /readyz` (DB check) |
| `python -m witness.worker` | none | jobs, deferred replies, outbound Telegram/WhatsApp sends |
| `llama-server` (Qwen3-1.7B Q4_K_M) | 8080 (loopback only) | the router's local light-tier fallback |

`supervise.py` starts all three, restarts any that crashes (backoff capped at 30s), and checks at boot
whether `TIGER_DB_URL` is reachable. The database is Tiger Cloud. The Space keeps no state: its disk is
wiped on every restart.

All settings come from **Space secrets/variables** (Settings → Variables and secrets). Nothing secret is
built into the image. The full list and steps are in `DEPLOY_HF.md` in the source repo
(`tiger-witness/deploy/hf-space/DEPLOY_HF.md`).

Keep-alive: free CPU Basic Spaces sleep after 48 h without traffic. The Cloudflare Worker ingress pings
`/healthz` every 6 h and queues webhooks while the Space wakes.
