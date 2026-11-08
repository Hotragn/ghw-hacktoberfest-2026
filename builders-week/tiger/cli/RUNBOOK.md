# Tiger CLI runbook — MLH Builders Week Challenge 3

Official references:

- [Tiger CLI reference](https://www.tigerdata.com/docs/reference/tiger-cloud/tiger-cli)
- [Tiger CLI and MCP overview](https://www.tigerdata.com/docs/learn/tiger-cli-mcp)

**Live execution:** run only after **you** approve Tiger Cloud sign-in and service use. This agent does not provision services or push commits without direct user approval.

## Prerequisites

1. Install Tiger CLI: [reference](https://www.tigerdata.com/docs/reference/tiger-cloud/tiger-cli)
2. Authenticate:

```bash
tiger auth login
# or: tiger auth login --headless
```

3. **Use an existing free service** or create one with explicit **free shared** compute (do not rely on plan defaults):

```bash
tiger service list
# Only if you have verified your plan allows free shared compute in us-east-1:
tiger service create --name ghw-builders-week-tiger \
  --region us-east-1 --cpu shared --memory shared
```

Per the CLI reference, free services require `--region us-east-1` with `--cpu shared` and `--memory shared`. Omitting these flags can create **billable** compute depending on account plan. **Do not run `service create` until you confirm billing/plan with Tiger Console.**

4. Export service name (never commit passwords):

```bash
export TIGER_SERVICE_NAME='your-existing-or-new-free-service'
```

## Connectivity checks

```bash
tiger db ping "$TIGER_SERVICE_NAME"
tiger db uri "$TIGER_SERVICE_NAME"
tiger db extensions list "$TIGER_SERVICE_NAME"
```

## Apply SQL bundle (after approval)

```bash
cd builders-week/tiger
./scripts/run_live.sh
```

Files run in order including generated `sql/04b_import_alert_embeddings.sql`. Each `-f` is a separate session; earlier files commit before later ones fail.

## Verification (read-only)

```bash
tiger db query "$TIGER_SERVICE_NAME" --read-only -f queries/verify_extensions.sql
tiger db query "$TIGER_SERVICE_NAME" --read-only -f queries/verify_hypertable_chunks.sql
tiger db query "$TIGER_SERVICE_NAME" --read-only -f queries/verify_vector_index.sql
tiger db query "$TIGER_SERVICE_NAME" --read-only -f queries/similarity_filtered_time.sql
```

## External embeddings (optional)

If you supply a vetted model embedding CSV (no agent model API):

```bash
python3 scripts/validate_embedding_csv.py data/your_embeddings.csv
# then adapt 04b import or COPY after validation
```

Default fixtures use **256-d non-semantic lexical hashes** only.
