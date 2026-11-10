#!/usr/bin/env python3
"""Validate an external vetted embedding CSV (no model calls).

Checks finite numeric coordinates, required fields, severity range, duplicate fixture keys.
Does not validate semantic model provenance — operator must attest that separately.
"""
from __future__ import annotations

import argparse
import csv
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import DIM, FIXTURE_BATCH  # noqa: E402

REQUIRED = {
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


def parse_vector_literal(s: str, dim: int) -> list[float]:
    s = s.strip()
    if not s.startswith("[") or not s.endswith("]"):
        raise ValueError(f"embedding must be [f1,f2,...] got {s[:48]}...")
    inner = s[1:-1].strip()
    if not inner:
        raise ValueError("empty embedding vector")
    parts = [p.strip() for p in inner.split(",")]
    if len(parts) != dim:
        raise ValueError(f"expected {dim} dimensions, got {len(parts)}")
    out: list[float] = []
    for i, part in enumerate(parts):
        if not part:
            raise ValueError(f"empty coordinate at index {i}")
        if part.lower() in ("nan", "inf", "-inf", "infinity", "-infinity"):
            raise ValueError(f"non-finite literal at index {i}: {part!r}")
        try:
            v = float(part)
        except ValueError as e:
            raise ValueError(f"invalid float at index {i}: {part!r}") from e
        if isinstance(v, bool):  # bool is subclass of int in Python
            raise ValueError(f"boolean not allowed at index {i}")
        if not math.isfinite(v):
            raise ValueError(f"non-finite value at index {i}: {part!r}")
        out.append(v)
    return out


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("csv_path")
    p.add_argument("--dim", type=int, default=DIM)
    p.add_argument("--require-fixture-batch", default=FIXTURE_BATCH)
    args = p.parse_args()
    seen_keys: set[tuple[str, str]] = set()
    with open(args.csv_path, newline="", encoding="utf-8") as f:
        r = csv.DictReader(f)
        if not REQUIRED.issubset(set(r.fieldnames or [])):
            missing = REQUIRED - set(r.fieldnames or [])
            print(f"Missing columns: {sorted(missing)}", file=sys.stderr)
            return 2
        n = 0
        for line_no, row in enumerate(r, start=2):
            fk = (row["recorded_at"].strip(), row["fixture_key"].strip())
            if not fk[1]:
                print(f"line {line_no}: empty fixture_key", file=sys.stderr)
                return 2
            if fk in seen_keys:
                print(f"line {line_no}: duplicate (recorded_at, fixture_key)", file=sys.stderr)
                return 2
            seen_keys.add(fk)
            sev = int(row["severity"])
            if sev < 1 or sev > 5:
                print(f"line {line_no}: severity out of range", file=sys.stderr)
                return 2
            fb = row.get("fixture_batch") or ""
            if args.require_fixture_batch and fb != args.require_fixture_batch:
                print(
                    f"line {line_no}: fixture_batch {fb!r} != {args.require_fixture_batch!r}",
                    file=sys.stderr,
                )
                return 2
            parse_vector_literal(row["embedding"], args.dim)
            n += 1
    print(f"OK: {n} rows, dim={args.dim}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
