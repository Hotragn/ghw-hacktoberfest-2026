# Portable archive (local VM — review fixes)

**Not pushed to GitHub** until user approves.

| Artifact | Path |
|----------|------|
| Corrected tarball | `/opt/cursor/artifacts/builders-week-tiger-review-fixes-2026-11-08.tar.gz` |
| Prior tarball (pre-review-fix) | `/opt/cursor/artifacts/builders-week-tiger-2026-11-08.tar.gz` |

Recreate tarball after edits:

```bash
tar -czf /opt/cursor/artifacts/builders-week-tiger-review-fixes-2026-11-08.tar.gz \
  -C /workspace builders-week/tiger
```

Extract elsewhere:

```bash
tar -xzf builders-week-tiger-review-fixes-2026-11-08.tar.gz
```

Excludes: `.env`, `__pycache__`, `*.pyc` (via `.gitignore`; tarball from clean tree recommended).
