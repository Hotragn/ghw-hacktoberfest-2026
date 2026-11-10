#!/usr/bin/env python3
"""Generate all-MiniLM-L6-v2 (384-d) semantic embeddings for fixture SQL/CSV.

Offline on CPU after first model download (Hugging Face). No paid embedding API.
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

from fixtures import DIM, FIXTURE_BATCH, MODEL_ID, QUERY_PHRASES, ROWS

ROOT = Path(__file__).resolve().parents[1]
OUT_CSV = ROOT / "data" / "alert_embeddings_sample.csv"
OUT_SQL = ROOT / "sql" / "04b_import_alert_embeddings.sql"
OUT_QUERY_JSON = ROOT / "data" / "query_vectors.json"


def fixture_key(device_id: str, recorded_at_iso: str) -> str:
    return f"{device_id}|{recorded_at_iso}"


def vec_literal(v: list[float]) -> str:
    return "[" + ",".join(f"{x:.6f}" for x in v) + "]"


def sql_ts(iso: str) -> str:
    return iso.replace("T", " ").replace("+00:00", "+00")


def load_model():
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(MODEL_ID)


def encode_texts(model, texts: list[str]) -> list[list[float]]:
    vecs = model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
    return [list(map(float, row)) for row in vecs]


def _write_query_sql_files(qv: dict[str, str]) -> None:
    qdir = ROOT / "queries"
    cooling = qv["cooling_fan_reference"]
    thermal = qv["thermal_critical_reference"]
    soft = qv["soft_warning_reference"]
    dim = DIM
    (qdir / "similarity_cosine.sql").write_text(
        f"""-- Generated semantic query vectors ({MODEL_ID}, {dim}-d).
SET search_path TO builders_week, public;

WITH q AS (
  SELECT '{cooling}'::vector({dim}) AS query_vec
)
SELECT
  a.recorded_at,
  a.site,
  a.category,
  a.severity,
  a.summary_text,
  (a.embedding <=> q.query_vec) AS cosine_distance,
  (1 - (a.embedding <=> q.query_vec))::double precision AS cosine_similarity
FROM alert_embeddings a, q
ORDER BY a.embedding <=> q.query_vec
LIMIT 5;
""",
        encoding="utf-8",
    )
    (qdir / "similarity_l2.sql").write_text(
        f"""SET search_path TO builders_week, public;

WITH q AS (
  SELECT '{cooling}'::vector({dim}) AS query_vec
)
SELECT
  a.recorded_at,
  a.site,
  a.summary_text,
  (a.embedding <-> q.query_vec) AS l2_distance
FROM alert_embeddings a, q
ORDER BY a.embedding <-> q.query_vec
LIMIT 5;
""",
        encoding="utf-8",
    )
    (qdir / "similarity_filtered_time.sql").write_text(
        f"""-- Similarity + time range filter.
SET search_path TO builders_week, public;

WITH q AS (
  SELECT '{thermal}'::vector({dim}) AS query_vec
)
SELECT
  a.recorded_at,
  a.device_id,
  a.summary_text,
  (a.embedding <=> q.query_vec) AS cosine_distance
FROM alert_embeddings a, q
WHERE a.recorded_at >= TIMESTAMPTZ '2026-11-02 00:00:00+00'
  AND a.recorded_at <  TIMESTAMPTZ '2026-11-03 00:00:00+00'
ORDER BY a.embedding <=> q.query_vec
LIMIT 5;
""",
        encoding="utf-8",
    )
    (qdir / "similarity_filtered_metadata.sql").write_text(
        f"""-- Similarity + metadata filters (site, severity, tags).
SET search_path TO builders_week, public;

WITH q AS (
  SELECT '{soft}'::vector({dim}) AS query_vec
)
SELECT
  a.recorded_at,
  a.site,
  a.severity,
  a.tags,
  a.summary_text,
  (a.embedding <=> q.query_vec) AS cosine_distance
FROM alert_embeddings a, q
WHERE a.site = 'lab-east'
  AND a.severity >= 3
  AND 'thermal' = ANY (a.tags)
ORDER BY a.embedding <=> q.query_vec
LIMIT 10;
""",
        encoding="utf-8",
    )
    (qdir / "join_timeseries_vector.sql").write_text(
        f"""-- Closest alert in ±6h window by cosine distance to semantic query vector.
SET search_path TO builders_week, public;

WITH q AS (
  SELECT '{thermal}'::vector({dim}) AS query_vec
)
SELECT
  d.recorded_at,
  d.device_id,
  d.event_type,
  d.message AS event_message,
  a.summary_text AS closest_alert_by_vector_distance,
  a.cosine_distance
FROM device_events d
CROSS JOIN q
LEFT JOIN LATERAL (
  SELECT
    ae.summary_text,
    (ae.embedding <=> q.query_vec) AS cosine_distance
  FROM alert_embeddings ae
  WHERE ae.device_id = d.device_id
    AND ae.recorded_at >= d.recorded_at - INTERVAL '6 hours'
    AND ae.recorded_at <= d.recorded_at + INTERVAL '6 hours'
  ORDER BY ae.embedding <=> q.query_vec, ae.recorded_at
  LIMIT 1
) a ON TRUE
WHERE d.severity >= 3
  AND d.fixture_batch = 'bw2026-demo-v1'
ORDER BY d.recorded_at
LIMIT 15;
""",
        encoding="utf-8",
    )


def write_outputs(model) -> None:
    summaries = [r[5] for r in ROWS]
    embeddings = encode_texts(model, summaries)
    by_summary = dict(zip(summaries, embeddings))

    query_keys = list(QUERY_PHRASES.keys())
    query_texts = [QUERY_PHRASES[k] for k in query_keys]
    query_vecs = encode_texts(model, query_texts)
    qv = {k: vec_literal(v) for k, v in zip(query_keys, query_vecs)}

    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    value_rows: list[str] = []
    with OUT_CSV.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(
            [
                "recorded_at", "fixture_key", "device_id", "site", "category",
                "severity", "summary_text", "tags", "embedding", "fixture_batch",
            ]
        )
        for row, emb in zip(ROWS, embeddings):
            ts, dev, site, cat, sev, summary, tags = row
            fkey = fixture_key(dev, ts)
            tags_list = tags.split(",")
            lit = vec_literal(emb)
            w.writerow([ts, fkey, dev, site, cat, sev, summary, ";".join(tags_list), lit, FIXTURE_BATCH])
            value_rows.append(
                f"  ('{sql_ts(ts)}', '{fkey}', '{dev}', '{site}', '{cat}', {sev}, "
                f"{summary!r}, ARRAY{tags_list!r}, '{lit}'::vector({DIM}), '{FIXTURE_BATCH}')"
            )

    sql_lines = [
        f"-- Generated by scripts/embed_semantic.py ({MODEL_ID}, {DIM}-d).",
        "-- Idempotent: INSERT ON CONFLICT DO NOTHING (no DELETE).",
        "SET search_path TO builders_week, public;",
        "",
        "INSERT INTO alert_embeddings",
        "  (recorded_at, fixture_key, device_id, site, category, severity, summary_text, tags, embedding, fixture_batch)",
        "VALUES",
        ",\n".join(value_rows),
        "ON CONFLICT (recorded_at, fixture_key) DO NOTHING;",
    ]
    OUT_SQL.write_text("\n".join(sql_lines) + "\n", encoding="utf-8")

    meta = {
        "_note": f"Semantic embeddings from {MODEL_ID}",
        "model": MODEL_ID,
        "dimensions": DIM,
        **qv,
    }
    OUT_QUERY_JSON.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    _write_query_sql_files(qv)
    return by_summary


def main() -> int:
    model = load_model()
    write_outputs(model)
    print(f"Wrote {OUT_CSV}", file=sys.stderr)
    print(f"Wrote {OUT_SQL}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
