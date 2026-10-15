# Deploying Witness on Tiger Cloud

## 1. Create the service (operator, once)
```bash
curl -fsSL https://cli.tigerdata.com | sh && tiger auth login
tiger service create --name witness-prod --cpu shared      # or a dedicated size
tiger db uri                                                # admin URI (tsdbadmin), keep it secret
tiger db query -c "SELECT extname FROM pg_available_extensions WHERE name IN ('timescaledb','vector','vectorscale')"
```

## 2. Migrate as the owner (CI/CD job, not the app)
```bash
TIGER_DB_URL="$ADMIN_URI" python -m witness.setup_db       # idempotent, advisory-locked, checksum-tracked
psql "$ADMIN_URI" -v app_password="'$(openssl rand -base64 32)'" -f sql/roles.sql
```
Migrations live in `sql/NN_*.sql`. A changed file that was already applied is rejected (add a new `NN_` file instead). The exception is `05_queries.sql`, which is repeatable and re-applies when its checksum changes.

## 3. Run the app as `witness_app`
Required environment variables:
| Var | Value |
|---|---|
| `TIGER_DB_URL` | `postgres://witness_app:<pw>@<host>:<port>/tsdb?sslmode=require` |
| `WITNESS_SIGNING_KEY` | `openssl rand -hex 32` (secret manager) |
| `WITNESS_ENV` | `prod` |
| `WITNESS_COOKIE_SECURE` | `true` (serve over HTTPS only) |
| `WITNESS_ALLOW_REGISTRATION` | `true` or `false` (invite-only) |
| `WITNESS_RATE_PER_MIN` / `WITNESS_RATE_BURST` | defaults 120 / 40 |
| `LOG_FORMAT` / `LOG_LEVEL` | `json` / `INFO` |

```bash
docker build -t witness:$(git rev-parse --short HEAD) .
docker run -p 8103:8103 --env-file prod.env --read-only witness:<sha>
```
Put it behind a TLS-terminating proxy (Fly, Cloud Run, ECS + ALB, …). Use `/healthz` for liveness and `/readyz` for readiness (DB ping). Logs are JSON lines with a `request_id`, which is also returned in the `x-request-id` header.

## 4. Operations
- Caggs refresh on policies (15 min / 1 h / 5 min). Compression starts at 30/60 days and retention drops raw memory after 400 days. Receipts are never dropped.
- Back up with Tiger Cloud's point-in-time recovery. A daily `GET /api/receipts/verify` per user (or `SELECT * FROM witness.verify_chain(user)`) proves integrity.
- Scale out: the app is stateless except for the in-process rate limiter (see SECURITY.md). Keep `WITNESS_DB_POOL × replicas` below the service's connection limit, or use Tiger's connection pooler.
