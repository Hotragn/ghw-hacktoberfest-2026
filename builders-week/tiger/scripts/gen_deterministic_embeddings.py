#!/usr/bin/env python3
"""Build 16-d deterministic vectors for demo pgvector queries.

NOT semantic embeddings: derived from hashed character n-grams of summary_text plus
metadata fields. Same input always yields the same unit vector. Suitable for
exercising pgvector/Timescale SQL only.
"""
from __future__ import annotations

import csv
import hashlib
import math
import re
import sys
from pathlib import Path

DIM = 16
ROOT = Path(__file__).resolve().parents[1]
OUT_CSV = ROOT / "data" / "alert_embeddings_sample.csv"


def embed_text(
    summary: str,
    *,
    site: str,
    category: str,
    severity: int,
    device_id: str,
) -> list[float]:
    payload = f"{site}|{category}|{severity}|{device_id}|{summary.lower().strip()}"
    vec = [0.0] * DIM
    tokens = re.findall(r"[a-z0-9]+", payload)
    for tok in tokens:
        h = hashlib.sha256(tok.encode()).digest()
        for i in range(DIM):
            # Map bytes to [-1, 1] contribution per dimension
            b = h[i % len(h)]
            vec[i] += (b / 127.5) - 1.0
    norm = math.sqrt(sum(x * x for x in vec)) or 1.0
    return [round(x / norm, 6) for x in vec]


def vec_literal(v: list[float]) -> str:
    return "[" + ",".join(f"{x:.6f}" for x in v) + "]"


ROWS = [
    ("2026-11-02T12:00:00+00:00", "sensor-a1", "lab-east", "thermal", 5,
     "high temperature alert threshold exceeded", "thermal,critical,lab-east"),
    ("2026-11-02T12:05:00+00:00", "sensor-a1", "lab-east", "thermal", 5,
     "cooling fan failure suspected", "thermal,hardware,lab-east"),
    ("2026-11-04T08:02:00+00:00", "sensor-a1", "lab-east", "power", 4,
     "power quality event logged", "power,lab-east"),
    ("2026-11-01T16:45:00+00:00", "sensor-b2", "lab-east", "physical", 4,
     "door held open 90 seconds", "access,lab-east"),
    ("2026-11-04T14:00:00+00:00", "sensor-b2", "lab-east", "air-quality", 3,
     "co2 ppm elevated during meeting", "co2,occupancy,lab-east"),
    ("2026-11-07T09:15:00+00:00", "sensor-a1", "lab-east", "thermal", 3,
     "soft warning below critical threshold", "thermal,warning,lab-east"),
    ("2026-11-03T13:40:00+00:00", "sensor-a1", "lab-east", "thermal", 2,
     "recovered after maintenance", "thermal,maintenance,lab-east"),
    ("2026-11-05T12:20:00+00:00", "sensor-d4", "warehouse", "access", 2,
     "loading dock opened", "access,warehouse"),
    ("2026-11-06T15:00:00+00:00", "sensor-c3", "roof-north", "thermal", 3,
     "afternoon heat on roof sensor", "thermal,roof-north,weather"),
    ("2026-11-02T15:30:00+00:00", "sensor-d4", "warehouse", "motion", 3,
     "motion detected aisle 3", "motion,warehouse,security"),
]


def main() -> int:
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    with OUT_CSV.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(
            "recorded_at,device_id,site,category,severity,summary_text,tags,embedding"
            .split(",")
        )
        for ts, dev, site, cat, sev, summary, tags in ROWS:
            tags_list = tags.split(",")
            emb = embed_text(summary, site=site, category=cat, severity=sev, device_id=dev)
            w.writerow([ts, dev, site, cat, sev, summary, ";".join(tags_list), vec_literal(emb)])
            if "--print-sql" in sys.argv:
                print(
                    f"  ('{ts.replace('T', ' ').replace('+00:00', '+00')}', '{dev}', "
                    f"'{site}', '{cat}', {sev}, '{summary}', ARRAY{tags_list!r}, "
                    f"'{vec_literal(emb)}'::vector),"
                )
    print(f"Wrote {OUT_CSV}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
