from scamshield.detector import score, THRESHOLD
from scamshield.storylines import STORYLINES, CATEGORY_LABELS

QUIET = dict(night_call_minutes=0, intl_calls=0, night_door_events=0, sleep_disruption=0.1, kiosk_visits=0,
             kiosk_usd=0, gift_card_usd=0, wire_usd=0)


def test_quiet_household_scores_zero():
    s, reasons, narrative = score(QUIET, [])
    assert s == 0 and reasons == [] and "normal" in narrative


def test_pig_butchering_pattern_crosses_threshold():
    f = {**QUIET, "night_call_minutes": 300, "intl_calls": 9, "kiosk_visits": 3, "kiosk_usd": 9000}
    s, reasons, _ = score(f, [{"gap_pct": 30.0}])
    assert s >= THRESHOLD and any("kiosk" in r for r in reasons) and any("Coinbase" in r for r in reasons)


def test_score_is_capped():
    f = {k: (10**6 if isinstance(v, (int, float)) else v) for k, v in QUIET.items()}
    assert score(f, [{"gap_pct": 99.0}])[0] <= 1.0


def test_storylines_have_known_categories():
    assert STORYLINES and all(cat in CATEGORY_LABELS for _, cat, _, _ in STORYLINES)
