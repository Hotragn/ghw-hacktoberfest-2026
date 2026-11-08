# Builders Week Tiger — status (2026-11-08)

## Completed in this branch (preparation / mock)

- [x] Isolated `builders_week` schema SQL (extensions, plain table, import, hypertable conversion)
- [x] Hybrid vector hypertable + pgvector / pgvectorscale index fallback
- [x] Capped sample CSV datasets with **labeled non-semantic** deterministic embeddings
- [x] Parameterized verification and similarity query files
- [x] Tiger CLI runbook (Challenge 3) using **documented** commands only
- [x] Local unit tests (`pytest`) — **MOCK**, no database
- [x] `verify_local.sh` and optional `run_live.sh` (fails closed without env)

## Not completed here (requires live Tiger Cloud + user credentials)

- [ ] Provision / confirm free Tiger Cloud instance (Challenge 1 quickstart)
- [ ] `tiger auth login` on operator machine
- [ ] Execute `scripts/run_live.sh` or runbook steps end-to-end
- [ ] Capture redacted screenshots / CLI output for MLH submission
- [ ] Submit MLH challenge forms (explicitly out of scope for this agent run)

## Test results (this environment — MOCK only)

Recorded 2026-11-08 UTC on the cloud agent VM (no Tiger Cloud credentials):

```
$ cd builders-week/tiger && python3 -m unittest discover -s tests -p 'test_*.py' -v
... 6 tests ... OK

$ ./scripts/verify_local.sh
[mock] unittest — OK
[mock] SQL bundle file count — OK (7 files)
[mock] sample data row caps — OK (30 device rows, 10 alert rows)
[mock] regenerate embeddings CSV — OK
OK — local/mock checks passed (not a live Tiger Cloud proof).
```

Live `tiger db query` / `run_live.sh` was **not** executed in this environment.

## Remaining live checklist

1. `tiger service list` — note service name → `export TIGER_SERVICE_NAME=...`
2. `tiger db ping "$TIGER_SERVICE_NAME"`
3. `tiger db extensions list "$TIGER_SERVICE_NAME"` — expect `timescaledb`, `vector`; `vectorscale` on Tiger Cloud
4. Run `sql/*.sql` in order via `run_live.sh` or runbook
5. Run all `queries/*.sql` and save output (redact host/password)
6. Optional: `tiger db query ... -f queries/similarity_filtered_metadata.sql` with different `$1` / time bounds
