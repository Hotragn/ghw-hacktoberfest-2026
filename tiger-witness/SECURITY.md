# Security model

## Threats addressed
| Threat | Control |
|---|---|
| Agent acts beyond what the user allowed | Scoped mandates (action, counterparty glob, per-action max, rolling 30-day cap, uses, expiry, daily budget) checked by a pure policy engine before every adapter call |
| Agent "invents" facts | Evidence binding: uncited facts become `assumptions`, and any assumption forces approval |
| Sensitive data disclosure | Protected classes (`address`, `health`, `financial`) need an explicit `disclose` grant on a matching mandate |
| Scam-originated requests | Inbound messages are scored against scam storylines (pgvector) + hint terms; a score ≥ 0.55 blocks the action |
| Malicious or drifting tools | Tool reputation ≥ 0.80 and no drift flag, or the action is blocked |
| Repudiation / tampering | Per-user SHA-256 hash chain (checked in SQL), HMAC-SHA256 signature over each hash, append-only trigger, no UPDATE/DELETE grant for the app role |
| Double execution on retry | Adapters are idempotent on `idempotency_key = action_id`; approvals are unique per action (`approvals` PK) |
| Account takeover | scrypt password hashes (N=2^14, r=8, p=1), 12-char minimum, lockout after 5 failures for 15 min, per-IP login rate limit (10/min) |
| Session theft | 256-bit random tokens; **only sha256(token) is stored**; HttpOnly + SameSite=Strict cookie (Secure required in prod) or Bearer header; server-side expiry and logout delete |
| CSRF | SameSite=Strict cookie; JSON-only bodies; Bearer tokens for API clients |
| Cross-user access | Every query filters by the session's `user_id`; covered by `test_auth_required_and_isolation` |
| Abuse / DoS | Token-bucket rate limit per client IP (default 120/min, burst 40) on all non-health routes; bounded `limit` params; request size bounds via pydantic |
| Injection | asyncpg parameterised queries only; replay params use an allow-list; mandate counterparty limited by regex |
| Information leaks | Uniform JSON error envelope with request id; unhandled errors return a generic 500 and log the stack server-side only |
| Clickjacking / sniffing | `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer` |

## Secrets
All secrets come from environment variables (`TIGER_DB_URL`, `WITNESS_SIGNING_KEY`). Nothing is committed (`.env` is gitignored and dockerignored). With `WITNESS_ENV=prod` the app refuses to start unless the signing key is at least 32 characters and secure cookies are on. Rotate the signing key by adding a `key_id` to receipts (planned). Old receipts stay verifiable with the old key.

## Least-privilege database role
Run migrations as the schema owner (`tsdbadmin`) from CI/CD only. The app connects as `witness_app` (`sql/roles.sql`), which can INSERT into ledgers and memory, UPDATE only mandates/accounts/users, DELETE only sessions, and has **no UPDATE/DELETE on receipts**.

## Known limits (honest)
- The rate limiter is in-process. With more than one replica, put limits at the edge (Cloudflare, an API gateway) or move to Redis.
- Receipts use HMAC (a server-held key). The production path is per-user Ed25519 keys on the user's device, co-signing approvals, so even the operator cannot forge consent.
- The scam score is a heuristic over keyless hashed embeddings. A real deployment should use a proper embedding model (pgai) and a maintained storyline feed.
- The demo password for seeded users is public. Never run `simulator --reset` against production.
