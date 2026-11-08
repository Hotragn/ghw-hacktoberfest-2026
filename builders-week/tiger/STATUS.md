# Builders Week Tiger — status (2026-11-08, post-review fixes)

## Local preparation (this VM)

- [x] Review P1/P2 SQL fixes applied under `builders-week/tiger/` only
- [x] 256-d non-semantic lexical embedding pipeline + `validate_embedding_csv.py`
- [x] 14 mock unittest tests + `verify_local.sh` (CSV/generator sync)
- [x] `__pycache__` removed; `.gitignore` added
- [ ] **Not pushed** — awaiting direct user approval (prior push was relayed only)
- [ ] **No live Tiger Cloud execution** in this environment

## NOT claimed complete

- Tiger Cloud quickstart / hypertable live proof (Challenge 1)
- Tiger CLI live query output (Challenge 3)
- pgvectorscale DiskANN live proof (Challenge 5)
- Semantic / model-generated embeddings (Challenge 5 AI wording)

Deterministic 256-d hashes exercise pgvector operators only.

## Mock test results (this VM)

```
python3 -m unittest discover -s tests -p 'test_*.py' -v  → 14 tests OK
./scripts/verify_local.sh                                 → OK
```

## Remaining gates (user / live)

1. Approve git push and Tiger Cloud sign-in
2. Confirm free plan; use existing service OR `tiger service create ... --region us-east-1 --cpu shared --memory shared`
3. `export TIGER_SERVICE_NAME=...` → `./scripts/run_live.sh`
4. Run `queries/verify_*.sql` and similarity queries; save redacted output
5. Optionally swap in vetted external embedding CSV after validation

## Portable artifact

See [`docs/ARTIFACTS.md`](docs/ARTIFACTS.md) for tarball path on this VM.
