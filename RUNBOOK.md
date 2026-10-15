# Runbook: from zero to every Tiger challenge screenshot

## 1. Install the Tiger CLI on Linux and log in (the user does this)
```bash
curl -fsSL https://cli.tigerdata.com | sh          # or: apt via packagecloud (see tiger-cli README)
tiger auth login            # OAuth in a browser. On the box you can use: tiger auth login --headless (enter the code in the browser)
#   or with API keys: tiger auth login --public-key ... --secret-key ...   (Console > Settings)
tiger auth status
```
## 2. Create one service for both projects
```bash
tiger service create --name ghw-tiger --cpu shared   # free/trial; waits until ready, becomes the default
tiger db uri                                          # put this in tiger-*/.env as TIGER_DB_URL
tiger db query -c "SELECT extname, extversion FROM pg_available_extensions WHERE name IN ('timescaledb','vector','vectorscale')"
```
## 3. Load schemas and data
```bash
cd tiger-tooltruth && python -m tooltruth.setup_db && python -m tooltruth.simulator --backfill-hours 48 && python -m tooltruth.fingerprint --windows 48
cd ../tiger-scamshield && python -m scamshield.setup_db && python -m scamshield.simulator --backfill-days 14 && python -m scamshield.detector
```
## 4. Screenshots
| Challenge | What to capture |
|---|---|
| (a) Tiger CLI + MCP | `tiger mcp install copilot` (or claude-code/cursor), then ask in natural language: "list my Tiger services", "run tooltruth.behaving_like_known_bad('24 hours', NULL, 0.05)". Screenshot the agent's MCP tool calls and the results |
| (b) service + hypertable + reusable queries | `tiger service list` + `tiger db query -c "SELECT * FROM timescaledb_information.hypertables"` + `SELECT * FROM tooltruth.tool_health('24h') LIMIT 10` |
| (c) continuous aggregates | `SELECT * FROM timescaledb_information.continuous_aggregates` + `SELECT * FROM tooltruth.tool_hourly ORDER BY bucket DESC LIMIT 10` |
| (d) simulated IoT + metadata | ScamShield: `SELECT * FROM scamshield.devices` + `SELECT * FROM scamshield.signals_hourly ...` + dashboard :8102 |
| (e) real-time financial ingestion | Run `python -m tooltruth.simulator --live` / `python -m scamshield.simulator --live` and show the logs + `SELECT * FROM tooltruth.eth_usd_1m ORDER BY bucket DESC` / `scamshield.btc_1m` updating |
| (f) pgvector/pgvectorscale RAG | `\d+ tooltruth.tool_behavior` (diskann index) + `tooltruth.behaving_like_known_bad('24 hours','web',0.05)` + `scamshield.similar_storylines('hh-001')` |
| GitHub Copilot app / Copilot on a challenge | Copilot CLI in the repo: ask it to add the `tooltruth diff` command or run it. Screenshot. Then post a GitHub Discussion (needs approval) |
