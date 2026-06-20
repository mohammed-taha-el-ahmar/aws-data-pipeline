"""
Unit tests for lambda_query/handler.py.

All boto3 calls are patched — no AWS credentials or network needed.
"""

import json
import sys
from unittest.mock import MagicMock, patch

import pytest

pytestmark = pytest.mark.unit

WORKGROUP = "test-wg"
DATABASE = "dev"

# Helpers to build Redshift Data API field objects
_str = lambda v: {"stringValue": v}  # noqa: E731
_dbl = lambda v: {"doubleValue": v}  # noqa: E731
_null = {"isNull": True}

SAMPLE_ROW = [
    _str("2026-06-20T11:00:00+00:00"),  # ingested_at
    _dbl(48.86),  # latitude
    _dbl(2.36),  # longitude
    _dbl(21.5),  # temperature_c
    _dbl(6.2),  # wind_speed_kmh
    _dbl(55.0),  # humidity_pct
]


@pytest.fixture()
def handler(monkeypatch):
    """
    Import lambda_query.handler with env vars set and a fresh module import.
    Returns the (lambda_handler, mock_client) pair.
    """
    monkeypatch.setenv("REDSHIFT_WORKGROUP", WORKGROUP)
    monkeypatch.setenv("REDSHIFT_DATABASE", DATABASE)
    sys.modules.pop("lambda_query.handler", None)

    mock_client = MagicMock()
    with patch("boto3.client", return_value=mock_client):
        import lambda_query.handler as m  # noqa: PLC0415

        yield m.lambda_handler, mock_client

    sys.modules.pop("lambda_query.handler", None)


def _setup_client(mock_client, rows: list, status: str = "FINISHED"):
    """Configure mock_client to return a successful statement execution."""
    mock_client.execute_statement.return_value = {"Id": "stmt-123"}
    mock_client.describe_statement.return_value = {"Status": status}
    mock_client.get_statement_result.return_value = {"Records": rows}


# ─── Happy path ───────────────────────────────────────────────────────────────


def test_returns_200_with_data(handler):
    lambda_handler, client = handler
    _setup_client(client, [SAMPLE_ROW])

    result = lambda_handler({}, None)

    assert result["statusCode"] == 200
    body = json.loads(result["body"])
    assert body["temperature_c"] == 21.5
    assert body["wind_speed_kmh"] == 6.2
    assert body["humidity_pct"] == 55.0
    assert body["ingested_at"] == "2026-06-20T11:00:00+00:00"
    assert body["latitude"] == 48.86
    assert body["longitude"] == 2.36


def test_response_body_has_all_schema_keys(handler):
    lambda_handler, client = handler
    _setup_client(client, [SAMPLE_ROW])

    result = lambda_handler({}, None)
    body = json.loads(result["body"])

    expected = {
        "ingested_at",
        "latitude",
        "longitude",
        "temperature_c",
        "wind_speed_kmh",
        "humidity_pct",
    }
    assert set(body.keys()) == expected


def test_cors_header_on_200(handler):
    lambda_handler, client = handler
    _setup_client(client, [SAMPLE_ROW])

    result = lambda_handler({}, None)
    assert result["headers"]["Access-Control-Allow-Origin"] == "*"


# ─── Empty result ─────────────────────────────────────────────────────────────


def test_returns_404_when_no_rows(handler):
    lambda_handler, client = handler
    _setup_client(client, [])  # no rows yet

    result = lambda_handler({}, None)

    assert result["statusCode"] == 404
    body = json.loads(result["body"])
    assert "error" in body


def test_cors_header_on_404(handler):
    lambda_handler, client = handler
    _setup_client(client, [])

    result = lambda_handler({}, None)
    assert result["headers"]["Access-Control-Allow-Origin"] == "*"


# ─── Spectrum schema not created yet ─────────────────────────────────────────


def test_returns_503_when_spectrum_missing(handler):
    lambda_handler, client = handler
    client.execute_statement.return_value = {"Id": "stmt-456"}
    client.describe_statement.return_value = {
        "Status": "FAILED",
        "Error": "ERROR: relation 'spectrum.processed' does not exist",
    }

    result = lambda_handler({}, None)

    assert result["statusCode"] == 503
    body = json.loads(result["body"])
    assert "spectrum" in body["error"].lower() or "does not exist" in body.get("detail", "")


def test_cors_header_on_503(handler):
    lambda_handler, client = handler
    client.execute_statement.return_value = {"Id": "stmt-456"}
    client.describe_statement.return_value = {
        "Status": "FAILED",
        "Error": "relation spectrum.processed does not exist",
    }

    result = lambda_handler({}, None)
    assert result["headers"]["Access-Control-Allow-Origin"] == "*"


# ─── Generic Redshift failure ─────────────────────────────────────────────────


def test_returns_500_on_generic_failure(handler):
    lambda_handler, client = handler
    client.execute_statement.return_value = {"Id": "stmt-789"}
    client.describe_statement.return_value = {
        "Status": "FAILED",
        "Error": "syntax error at or near SELECT",
    }

    result = lambda_handler({}, None)
    assert result["statusCode"] == 500


def test_returns_500_on_unexpected_exception(handler):
    lambda_handler, client = handler
    client.execute_statement.side_effect = RuntimeError("network timeout")

    result = lambda_handler({}, None)
    assert result["statusCode"] == 500
    body = json.loads(result["body"])
    assert "error" in body


# ─── _field_value helper ──────────────────────────────────────────────────────
# Use the handler fixture so boto3.client is already patched when the module
# is imported — avoids NoRegionError from the module-level client creation.


def test_field_value_double(handler):
    import lambda_query.handler as m  # noqa: PLC0415 — already imported by fixture

    assert m._field_value({"doubleValue": 3.14}) == 3.14


def test_field_value_string(handler):
    import lambda_query.handler as m  # noqa: PLC0415

    assert m._field_value({"stringValue": "hello"}) == "hello"


def test_field_value_null(handler):
    import lambda_query.handler as m  # noqa: PLC0415

    assert m._field_value({"isNull": True}) is None


def test_field_value_long(handler):
    import lambda_query.handler as m  # noqa: PLC0415

    assert m._field_value({"longValue": 42}) == 42
