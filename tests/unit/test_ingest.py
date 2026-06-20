"""Unit tests for shared/ingest.py — no network, no AWS."""

import json
from unittest.mock import MagicMock, patch

import pytest

from shared.ingest import fetch_data, raw_object_key, to_raw_record

pytestmark = pytest.mark.unit

SAMPLE_PAYLOAD = {
    "latitude": 48.86,
    "longitude": 2.36,
    "current": {
        "temperature_2m": 21.5,
        "wind_speed_10m": 6.2,
        "relative_humidity_2m": 55,
    },
}


def test_to_raw_record_wraps_payload():
    record = to_raw_record(SAMPLE_PAYLOAD)
    assert record["source"] == "open-meteo"
    assert record["payload"] == SAMPLE_PAYLOAD
    assert "ingested_at" in record
    # ISO 8601 with timezone
    assert "+" in record["ingested_at"] or "Z" in record["ingested_at"]


def test_raw_object_key_format():
    key = raw_object_key()
    assert key.startswith("raw/year=")
    assert "/month=" in key
    assert "/day=" in key
    assert key.endswith(".json")


def test_raw_object_key_custom_prefix():
    key = raw_object_key(prefix="staging")
    assert key.startswith("staging/year=")


def test_fetch_data_parses_json():
    mock_response = MagicMock()
    mock_response.read.return_value = json.dumps(SAMPLE_PAYLOAD).encode()
    mock_response.__enter__ = lambda s: s
    mock_response.__exit__ = MagicMock(return_value=False)

    with patch("urllib.request.urlopen", return_value=mock_response):
        result = fetch_data("https://example.invalid/api")

    assert result == SAMPLE_PAYLOAD


def test_fetch_data_uses_default_url():
    """fetch_data should call the Open-Meteo URL by default."""
    mock_response = MagicMock()
    mock_response.read.return_value = json.dumps(SAMPLE_PAYLOAD).encode()
    mock_response.__enter__ = lambda s: s
    mock_response.__exit__ = MagicMock(return_value=False)

    with patch("urllib.request.urlopen", return_value=mock_response) as mock_open:
        fetch_data()
        called_url = mock_open.call_args[0][0]

    assert "open-meteo.com" in called_url
    assert "latitude=48.8566" in called_url
