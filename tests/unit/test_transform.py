"""Unit tests for shared/transform.py — pure Python, no AWS."""

import pytest

from shared.transform import transform_record

pytestmark = pytest.mark.unit

RAW_RECORD = {
    "ingested_at": "2026-06-20T11:00:00+00:00",
    "source": "open-meteo",
    "payload": {
        "latitude": 48.86,
        "longitude": 2.36,
        "current": {
            "temperature_2m": 21.5,
            "wind_speed_10m": 6.2,
            "relative_humidity_2m": 55,
        },
    },
}


def test_transform_extracts_all_fields():
    row = transform_record(RAW_RECORD)
    assert row["ingested_at"] == "2026-06-20T11:00:00+00:00"
    assert row["latitude"] == 48.86
    assert row["longitude"] == 2.36
    assert row["temperature_c"] == 21.5
    assert row["wind_speed_kmh"] == 6.2
    assert row["humidity_pct"] == 55


def test_transform_output_keys():
    row = transform_record(RAW_RECORD)
    expected_keys = {
        "ingested_at",
        "latitude",
        "longitude",
        "temperature_c",
        "wind_speed_kmh",
        "humidity_pct",
    }
    assert set(row.keys()) == expected_keys


def test_transform_missing_current_fields():
    """Fields absent in the API response should come through as None."""
    raw = {
        "ingested_at": "2026-06-20T11:00:00+00:00",
        "payload": {
            "latitude": 48.86,
            "longitude": 2.36,
            "current": {},  # all current fields missing
        },
    }
    row = transform_record(raw)
    assert row["temperature_c"] is None
    assert row["wind_speed_kmh"] is None
    assert row["humidity_pct"] is None


def test_transform_record_is_round_trippable():
    """The output should survive a JSON round-trip (no non-serialisable types)."""
    import json

    row = transform_record(RAW_RECORD)
    serialised = json.dumps(row)
    assert json.loads(serialised) == row
