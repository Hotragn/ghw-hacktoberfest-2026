#!/usr/bin/env python3
"""Mock IoT ping producer — inserts temperature readings at a steady interval.

Uses TIGER_DB_URL when set (PostgreSQL/Tiger Cloud). No external APIs.
"""
from __future__ import annotations

import argparse
import math
import os
import random
import time
from datetime import datetime, timezone

FIXTURE_BATCH = "bw2026-stream-live"


def fixture_key(device_id: str, recorded_at: datetime) -> str:
    return f"{device_id}|{recorded_at.isoformat()}"


def synthesize_reading(
    device_id: str,
    *,
    recorded_at: datetime | None = None,
    site: str = "lab-east",
    base_c: float = 22.0,
    rng: random.Random | None = None,
) -> dict:
    """One simulated sensor row (pure function — unit-testable)."""
    rng = rng or random.Random()
    ts = recorded_at or datetime.now(timezone.utc)
    drift = math.sin(ts.timestamp() / 120.0) * 1.5
    noise = rng.uniform(-0.4, 0.4)
    celsius = round(base_c + drift + noise, 2)
    battery = max(0, min(100, int(96 - (ts.timestamp() % 3600) / 3600 * 5 + rng.randint(-1, 1))))
    return {
        "recorded_at": ts,
        "fixture_key": fixture_key(device_id, ts),
        "device_id": device_id,
        "site": site,
        "celsius": celsius,
        "battery_pct": battery,
        "fixture_batch": FIXTURE_BATCH,
    }


def device_ids(count: int, prefix: str = "sensor") -> list[str]:
    return [f"{prefix}-{i}" for i in range(1, count + 1)]


def insert_reading(conn, row: dict) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO bw2026_stream.iot_readings
              (recorded_at, fixture_key, device_id, site, celsius, battery_pct, fixture_batch)
            VALUES (%(recorded_at)s, %(fixture_key)s, %(device_id)s, %(site)s,
                    %(celsius)s, %(battery_pct)s, %(fixture_batch)s)
            ON CONFLICT (recorded_at, fixture_key) WHERE fixture_key IS NOT NULL
            DO NOTHING
            """,
            row,
        )


def run_loop(interval_sec: float, devices: list[str], dsn: str) -> None:
    import psycopg2

    rng = random.Random(42)
    with psycopg2.connect(dsn) as conn:
        conn.autocommit = True
        print(f"Streaming {len(devices)} devices every {interval_sec}s → bw2026_stream.iot_readings")
        while True:
            for dev in devices:
                row = synthesize_reading(dev, rng=rng)
                insert_reading(conn, row)
            time.sleep(interval_sec)


def main() -> int:
    p = argparse.ArgumentParser(description="Mock IoT producer for Tiger streaming demo")
    p.add_argument("--once", action="store_true", help="Insert one round and exit")
    p.add_argument("--interval", type=float, default=float(os.environ.get("IOT_INTERVAL_SEC", "2")))
    p.add_argument("--devices", type=int, default=int(os.environ.get("IOT_DEVICES", "3")))
    args = p.parse_args()
    dsn = os.environ.get("TIGER_DB_URL", "").strip()
    if not dsn:
        print("TIGER_DB_URL not set — export connection string or use .env.example", flush=True)
        return 1
    devs = device_ids(args.devices)
    if args.once:
        import psycopg2

        rng = random.Random(99)
        with psycopg2.connect(dsn) as conn:
            conn.autocommit = True
            for dev in devs:
                insert_reading(conn, synthesize_reading(dev, rng=rng))
        print(f"Inserted {len(devs)} readings")
        return 0
    run_loop(args.interval, devs, dsn)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
