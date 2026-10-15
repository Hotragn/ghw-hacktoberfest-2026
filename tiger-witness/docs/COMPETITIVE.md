# Competitive analysis: personal agents, October 2026

Research date: 2026-10-15. Context: NoCap VC's carousel on personal AI agents says the winners will own **where users already chat**, **permission to act on their data** and **a trusted way to pay**, and that the open layers are **memory, agent security, agent payments, vertical agents and local-language messaging**. This page compares the main launches against those layers and lists what Witness v2 builds for each gap.

## What the incumbents shipped
| | Instinct | Meta Muse | OpenAI dots | Vantic (library) | AP2 (protocol) |
|---|---|---|---|---|---|
| What it is | Invite-only personal agent. Plans trips, orders groceries, cancels subscriptions, and calls businesses from its own phone. $1B Series C at a $10B valuation (2026-09-28) [1][2][3] | Meta's personal agent in its own app and in WhatsApp. Uses connectors for email, calendar, payments, health and smart home. Runs in an isolated cloud VM per user [4][5][6] | Always-on agents powered by GPT-6 Astra. Each has its own cloud computer, ChatGPT memory and 4,000+ app plugins [7][8][9] | Zero-dependency TypeScript SDK. Signed spending mandates and hash-chained receipts [10] | Google's Agent Payments Protocol. v0.2 uses Checkout and Payment Mandates, each either open or closed, signed with SD-JWT [11][12] |
| Channels | SMS and voice calls [3] | Muse app and WhatsApp, US only [4] | ChatGPT web, mobile and desktop; updates in Slack and Teams [8][9] | n/a | n/a |
| Permission model | Account access, not published in detail | Asks before important actions such as sending email or buying. Checks run separately from the model [5] | Custom Rules (allow, approve, block) plus Auto-review [8] | Mandate with budget, per-transaction cap and counterparty allowlist [10] | Open mandates carry user constraints and the agent key (`cnf`). Closed mandates are bound to the checkout hash [11] |
| Memory | Not published | Data lives in the VM; backups [5] | ChatGPT memory; learns from feedback [8][9] | none | none |
| Proof of authorisation | Not published | Not published | Review in the app | Signed receipts, verifiable offline [10] | Mandates are verifiable credentials [11] |
| Known problems | Since 2 August 2026, EU AI Act Art. 50 requires an AI to say it is an AI when it calls people [3] | Reuters reported internal tests where the agent stalled and exposed sensitive data without authorisation [4] | Rollout limited to Pro/Business tiers, and not available in the EEA/UK/CH for Pro [9] | Not a rail; TypeScript only; no memory or channels [10] | A protocol, not a product; v0.1 and v0.2 are incompatible [12] |

## Gaps, and what Witness v2 builds for each
| Gap in the market | Witness v2 answer | Code |
|---|---|---|
| **Channel lock-in.** Muse means WhatsApp, dots means ChatGPT, Instinct means SMS. | One agent, many channels: **Telegram** (webhook secret, inline Approve/Deny buttons), **WhatsApp Business Cloud API** (verify-token handshake, `X-Hub-Signature-256`, interactive buttons), **iMessage** through a self-hosted BlueBubbles relay on the user's Mac, and an **HMAC-signed generic webhook**. Approvals work inside the chat. | `witness/channels.py` |
| **Local-language messaging** is named as an open layer. | Detects the language of every message (26 languages, script- and stopword-based, no dependencies). The agent replies in that language. System phrases are translated, so it works with the offline planner too. | `witness/i18n.py` |
| **Permission to act** is all or nothing ("Allow always"). | **Grants** scoped by tool glob × scope (read/write/spend) × data class. They expire, can be revoked, can have a use limit, and auto-approval is optional. Every call is gated in code outside the model, and every verdict gets a receipt. | `witness/consent.py`, `runtime.gate` |
| **Prompt injection.** Muse, dots and Instinct all read web pages, emails and invites. Meta notes that its checks run separately from the model [5]. | **Taint tracking plus argument provenance.** Once untrusted output enters the context, a write or spend can run without a human only if every argument value appears in text the user wrote. Tests use a deliberately *gullible* planner that obeys injected pages, so the tests show the firewall stops the action, not the model. | `witness/firewall.py`, `tests/test_v2_integration.py::test_prompt_injection_*` |
| **Trusted way to pay.** AP2 is a spec; Vantic is a TypeScript library with no rail. | AP2 v0.2-style flow. The user authorises an **open mandate** (merchant allowlist, per-transaction cap, rolling budget, expiry, optional human-present) through an authenticated session. The agent assembles a **closed mandate** bound to the checkout's SHA-256 and signs it with its own **ES256** key (non-deterministic, as AP2 requires). Budgets are enforced under an advisory lock, charges are idempotent, and the mock and **Stripe** rails are real adapters. | `witness/payments.py` |
| **Memory you can't see.** dots starts from ChatGPT memory; Muse keeps data in a VM. | **Episodic** memory: an `agent_events` hypertable. **Semantic** memory: `memory_items` with pgvector and DiskANN/HNSW. **Habits**: the `habits_daily` continuous aggregate. All memory can be listed, edited, pinned and forgotten in the UI. Forgetting is a hard delete that leaves only a hash tombstone and a receipt. | `witness/memory.py`, `sql/07,08` |
| **Tool ecosystem trust.** dots has 4,000 plugins. | A **MCP client** (streamable HTTP with SSE and session id, plus stdio) connects to any MCP server. Third-party write tools need reputation ≥ 0.8 in the cross-org reputation table, and drift blocks them. | `witness/mcp.py`, `witness/tools.py` |
| **Multi-tenant safety.** Muse relies on per-user VMs. | **FORCE ROW LEVEL SECURITY** on every v2 table, keyed on a per-transaction GUC. Tests show that a non-superuser with no WHERE clause sees zero rows of another tenant. | `witness/db.py`, `sql/07_agent_v2.sql` |
| **AI disclosure** (EU AI Act Art. 50) | Outbound email carries an "AI on my behalf" footer. | `tools.t_email_send` |

## Sources
1. TechCrunch, "Viral AI agent Instinct raises $1B Series C at a $10B valuation" (2026-09-28): https://techcrunch.com/2026/09/28/viral-ai-agent-instinct-raises-1b-series-c-at-a-10b-valuation/
2. Reuters, Instinct funding: https://www.reuters.com/technology/ai-agent-firm-instinct-raises-1-billion-latest-funding-round-2026-09-28/
3. The Next Web, Instinct and EU AI Act Art. 50: https://thenextweb.com/news/instinct-1bn-agent-calls-eu-rule
4. Reuters, Meta launches Muse: https://www.reuters.com/business/meta-launches-ai-agent-that-can-access-other-apps-send-emails-make-payments-2026-09-08/
5. Meta Help Center, Muse privacy, safety and security: https://www.meta.com/help/artificial-intelligence/1047255454427887/
6. Meta AI Research, How we built safety into Muse: https://research.meta.ai/blog/security-and-safety-for-ai-agents-our-approach-with-muse
7. OpenAI, Introducing dots: https://openai.com/index/introducing-dots/
8. ChatGPT, dots feature page: https://chatgpt.com/features/dots/
9. ChatGPT Learn, Meet dots: https://learn.chatgpt.com/docs/dots
10. Vantic: https://github.com/vanticlabs/vantic (see docs/ap2-and-standards.md)
11. AP2 specification: https://ap2-protocol.org/ap2/specification/
12. AP2 v0.1 vs v0.2 summary: https://skylineplatform.github.io/agentic-payments/protocols/ap2/
