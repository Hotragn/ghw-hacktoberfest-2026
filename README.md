# ghw-hacktoberfest-2026

MLH Global Hack Week: Hacktoberfest 2026 challenge projects.

## Challenges

- [First PR Finder](challenge-1-first-pr-finder/) — score a repository’s contributor readiness from 0 to 100 and recommend three starter issues. Static page, no build step.
- [SemVer model benchmark](challenge-2-model-benchmark/COMPARISON.md) — composer-2.5, claude-sonnet-5.5, and grok-4.7 each implemented SemVer. The [judge](challenge-2-model-benchmark/judge/) measured tests and fuzz agreement. [Results image](challenge-2-model-benchmark/results.png).

## Tiger Cloud projects

Three TimescaleDB + pgvector projects for the Tiger Data (Tiger Cloud) challenges. They share one Tiger Cloud service; each uses its own schema (`tooltruth`, `scamshield`, `witness`).

| Folder | Project | Tiger challenges |
|---|---|---|
| [`tiger-tooltruth/`](tiger-tooltruth/) | ToolTruth: MCP tool behaviour fingerprinting | hypertable + reusable queries, continuous aggregates, real-time financial ingestion (OpenRouter + Coinbase ETH), pgvector filtered similarity, Tiger CLI + MCP |
| [`tiger-witness/`](tiger-witness/) | Witness: a personal agent that proves every action (mandates, evidence-bound plans, signed receipts, what-if replay) | hypertables, hierarchical caggs, compression + retention, pgvector filtered recall, reusable SQL, per-user auth |
| [`tiger-scamshield/`](tiger-scamshield/) | ScamShield Home: consent-based elder-fraud early warning | simulated IoT sensor dataset + metadata, continuous aggregates, real-time Coinbase BTC, pgvector RAG over scam storylines |

- Each folder is self-contained: `requirements*.txt`, `Dockerfile`, `docker-compose.yml`, `tests/`, and `.env.example` (reads `TIGER_DB_URL`).
- Migrations: `python -m <pkg>.setup_db` runs checksum-tracked SQL migrations under an advisory lock.
- Least privilege: `sql/roles.sql` in each project.
- Setup and screenshots: [RUNBOOK.md](RUNBOOK.md). Deployment: [PRODUCTION.md](PRODUCTION.md) and [tiger-witness/DEPLOY.md](tiger-witness/DEPLOY.md).

## GitHub Skills

Completed GitHub Skills exercises for MLH Global Hack Week:

- [Introduction to Repository Management](https://github.com/Hotragn/skills-introduction-to-repository-management)
- [Getting Started with GitHub Copilot](https://github.com/Hotragn/skills-getting-started-with-github-copilot)
