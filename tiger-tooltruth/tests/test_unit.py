import argparse
import random
from datetime import datetime, timedelta, timezone
import pytest
from tooltruth.cli import iv
from tooltruth.fingerprint import features, KNOWN_BAD
from tooltruth.pricing import PriceBook, FALLBACK
from tooltruth.simulator import build_tools, make_call, COLS


def test_interval_parser():
    assert iv("30m") == timedelta(minutes=30) and iv("6h") == timedelta(hours=6) and iv("3d") == timedelta(days=3)
    with pytest.raises(argparse.ArgumentTypeError):
        iv("6 hours")


def test_pricebook_fallback_and_override():
    b = PriceBook()
    assert b.token_cost("unknown/model", 1000, 100) == pytest.approx(1000 * FALLBACK["prompt"] + 100 * FALLBACK["completion"])
    b.model_prices["m"] = {"prompt": 1e-6, "completion": 2e-6}
    assert b.token_cost("m", 10, 10) == pytest.approx(3e-5)


def test_build_tools_deterministic_and_planted():
    now = datetime.now(timezone.utc)
    a, b = build_tools(now), build_tools(now)
    assert [t.name for t in a] == [t.name for t in b] and len(a) == 47
    planted = {t.name: t.scenario for t in a if t.scenario != "normal"}
    assert len(planted) == 8 and set(planted.values()) == {"malicious", "swap", "drift"}


def test_malicious_flip_adds_exfil_host():
    now = datetime.now(timezone.utc)
    t = next(t for t in build_tools(now) if t.name == "web.summarize_url")
    row = make_call(t, now, PriceBook(), random.Random(1))
    assert len(row) == len(COLS) and t.flipped and t.version == "1.1.0"
    assert any("example-bad" in d for d in row[COLS.index("destinations")])


def test_features_shape_and_signal():
    base = dict(err=0.01, tmo=0.0, p50=200, p95=600, bytes=5000, bytes_max=20000, ndest=1, dests=1,
                new_dests=0, new_bytes=0, nver=1, cps=0.001, orgs=6)
    v = features(base)
    assert len(v) == 16 and all(len(k[1]) == 16 for k in KNOWN_BAD)
    bad = features({**base, "new_dests": 1, "bytes": 120000, "nver": 2, "new_bytes": 10**7})
    assert bad[8] == 1.0 and bad[14] == 1.0 and bad[15] == 1.0
