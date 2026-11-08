#!/usr/bin/env python3
"""Validate an external vetted embedding CSV (no model calls).

Required columns: recorded_at, fixture_key, device_id, site, category, severity,
summary_text, tags, embedding, fixture_batch
embedding must parse as vector(DIM) with DIM=256 by default.
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from gen_deterministic_embeddings import DIM, FIXTURE_BATCH  # noqa: E402

VEC_RE = re.compile(r"^\[[\d.,\-eE+]+\]$")


def parse_vector(s: str, dim: int) -> None:
    s = s.strip()
    if not VEC_RE.match(s):
        raise ValueError(f"embedding must look like [float,...] got {s[:40]}...")
    inner = s[1:-1]
    if not inner.strip():
        raise ValueError("empty embedding vector")
    parts = [p.strip() for p in inner.split(",")]
    if len(parts) != dim:
        raise ValueError(f"expected {dim} dimensions, got {len(parts)}")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("csv_path")
    p.add_argument("--dim", type=int, default=DIM)
    args = p.parse_args()
    with open(args.csv_path, newline="", encoding="utf-8") as f:
        r = csv.DictReader(f)
        required = {
            "recorded_at",
            "fixture_key",
            "device_id",
            "site",
            "category",
            "severity",
            "summary_text",
            "tags",
            "embedding",
            "fixture_batch",
        }
        if not required.issubset(set(r.fieldnames or [])):
            missing = required - set(r.fieldnames or [])
            print(f"Missing columns: {sorted(missing)}", file=sys.stderr)
            return 2
        n = 0
        for row in r:
            parse_vector(row["embedding"], args.dim)
            if row.get("fixture_batch") and row["fixture_batch"] != FIXTURE_BATCH:
                print(f"Warning: fixture_batch {row['fixture_batch']!r} != {FIXTURE_BATCH}", file=sys.stderr)
            n += 1
    print(f"OK: {n} rows, dim={args.dim}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
