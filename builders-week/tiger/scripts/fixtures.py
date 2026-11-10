"""Shared demo fixture rows for Tiger builders_week sample."""
from __future__ import annotations

FIXTURE_BATCH = "bw2026-demo-v1"
DIM = 384
MODEL_ID = "sentence-transformers/all-MiniLM-L6-v2"

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

QUERY_PHRASES = {
    "thermal_critical_reference": "critical overheating temperature alarm",
    "cooling_fan_reference": "cooling fan failure suspected",
    "soft_warning_reference": "soft warning below critical threshold",
}
