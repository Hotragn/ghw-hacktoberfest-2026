#!/usr/bin/env python3
"""Minimal Streamlit dashboard — reads continuous aggregate readings_1m.

Requires TIGER_DB_URL and applied SQL schema (bw2026_stream).
"""
from __future__ import annotations

import os

import pandas as pd
import psycopg2
import streamlit as st

QUERY = """
SELECT bucket, device_id, site, samples, avg_celsius, min_celsius, max_celsius
FROM bw2026_stream.readings_1m
WHERE bucket > now() - INTERVAL '30 minutes'
ORDER BY bucket DESC, device_id
LIMIT 200;
"""


@st.cache_resource
def get_conn():
    dsn = os.environ.get("TIGER_DB_URL", "").strip()
    if not dsn:
        return None
    return psycopg2.connect(dsn)


st.set_page_config(page_title="BW2026 IoT Stream", layout="wide")
st.title("Builders Week — mock IoT streaming aggregate")
st.caption("Source: bw2026_stream.readings_1m (Timescale continuous aggregate)")

if not os.environ.get("TIGER_DB_URL"):
    st.error("Set TIGER_DB_URL (see .env.example). Run SQL bundle, start iot_producer.py, refresh policy.")
    st.stop()

refresh = st.sidebar.slider("Auto-refresh seconds", 0, 30, 5)
if refresh:
    st.markdown(f'<meta http-equiv="refresh" content="{refresh}">', unsafe_allow_html=True)

conn = get_conn()
if conn is None:
    st.error("Could not connect")
    st.stop()

with conn.cursor() as cur:
    cur.execute(QUERY)
    cols = [d[0] for d in cur.description]
    rows = cur.fetchall()
df = pd.DataFrame(rows, columns=cols)

if df.empty:
    st.warning("No aggregate rows yet — run iot_producer.py and wait for refresh policy (~1 min).")
else:
    st.dataframe(df, use_container_width=True)
    st.line_chart(df.pivot_table(index="bucket", columns="device_id", values="avg_celsius"))

st.sidebar.write("Producer: `python3 iot_producer.py --once` or loop without --once")
