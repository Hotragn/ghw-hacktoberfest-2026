# Production deployment: ToolTruth and ScamShield on Tiger Cloud
(Witness has its own guide: `tiger-witness/DEPLOY.md`.)

## 1. Service and migrations
```bash
tiger service create --name ghw-tiger --cpu shared && tiger db uri          # admin URI, keep secret
cd tiger-tooltruth  && TIGER_DB_URL="$ADMIN_URI" python -m tooltruth.setup_db
cd ../tiger-scamshield && TIGER_DB_URL="$ADMIN_URI" python -m scamshield.setup_db
```
Migrations are tracked in `<schema>.schema_migrations`. Re-running them is a no-op. If an applied versioned file changes, the run fails (add a new `0N_*.sql` instead). `05_queries.sql` is repeatable.

## 2. Least-privilege roles (once, as owner)
```bash
psql "$ADMIN_URI" -v api_password="'$(openssl rand -base64 24)'" -v ingest_password="'$(openssl rand -base64 24)'" -f tiger-tooltruth/sql/roles.sql
psql "$ADMIN_URI" -v api_password="'...'" -v ingest_password="'...'" -f tiger-scamshield/sql/roles.sql
```
| Role | Used by | Can |
|---|---|---|
| `tooltruth_api` | dashboard/API | SELECT + query functions only |
| `tooltruth_ingest` | simulator, collectors, fingerprint job | SELECT + INSERT |
| `scamshield_api` | dashboard/API | SELECT; consent changes only via the audited `pause_monitoring` / `revoke_consent` (SECURITY DEFINER) |
| `scamshield_ingest` | simulator, detector | SELECT + INSERT, consent/feature functions |

## 3. Environment
| Var | ToolTruth | ScamShield |
|---|---|---|
| `TIGER_DB_URL` | `postgres://tooltruth_api:...@host:port/tsdb?sslmode=require` (ingest role for workers) | same with `scamshield_*` |
| `*_ENV` | `TOOLTRUTH_ENV=prod` | `SCAMSHIELD_ENV=prod` |
| `*_API_KEY` | required in prod, ≥ 24 chars (`openssl rand -hex 24`) | same |
| `*_RATE_PER_MIN` | default 240 | default 240 |
| `LOG_FORMAT` / `LOG_LEVEL` | `json` / `INFO` | same |
| `SCAMSHIELD_OFFLINE_BTC` | n/a | only for tests / air-gapped runs |

Clients send `Authorization: Bearer <key>` or `X-API-Key`. The dashboards ask for the key once per browser session. `/`, `/healthz` and `/readyz` stay open for probes.

## 4. Processes (same image, different commands)
| Project | API | Workers |
|---|---|---|
| ToolTruth | `uvicorn tooltruth.api:app --port 8101` | `python -m tooltruth.simulator --live`, `python -m tooltruth.fingerprint --loop 300` |
| ScamShield | `uvicorn scamshield.api:app --port 8102` | `python -m scamshield.simulator --live`, `python -m scamshield.detector --loop 300` |

`docker compose up --build` runs locally (`--profile demo` backfills, `--profile live` starts workers). In production, run the API behind TLS with `/readyz` as the readiness probe, and run the workers as single-replica jobs.

## 5. Security notes
- Secrets come only from env or a secret manager. `.env` is git- and docker-ignored.
- Rate limiting is in-process. For more than one API replica, enforce limits at the gateway.
- ScamShield data is sensitive by nature. Keep the API private (VPN/SSO proxy). The API key is a floor, not the whole access model.
- All data in these projects is simulated. Alerts and payments are never sent.
