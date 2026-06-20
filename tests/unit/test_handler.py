"""
Unit tests for lambda_ingest/handler.py.

Uses moto to mock S3 — no real AWS calls, no Docker required.
fetch_data is patched to avoid a network call.
"""

import json
from unittest.mock import patch

import boto3
import pytest
from moto import mock_aws

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

BUCKET = "test-data-lake"
REGION = "eu-west-3"


@pytest.fixture()
def handler(monkeypatch, aws_env):
    """
    Return the lambda_handler with its module-level s3 client and BUCKET
    replaced by moto-backed equivalents.

    Steps:
    1. Set DATA_LAKE_BUCKET *before* the import so module-level code can read it.
    2. Pop the module from sys.modules so it re-runs module-level code fresh.
    3. Import inside mock_aws() so the module-level boto3.client("s3") hits moto.
    """
    import sys

    monkeypatch.setenv("DATA_LAKE_BUCKET", BUCKET)
    sys.modules.pop("lambda_ingest.handler", None)  # force fresh import

    with mock_aws():
        import lambda_ingest.handler as m  # noqa: PLC0415 (import inside function)

        s3 = boto3.client("s3", region_name=REGION)
        s3.create_bucket(
            Bucket=BUCKET,
            CreateBucketConfiguration={"LocationConstraint": REGION},
        )
        # Patch module-level references so the handler uses our moto client
        monkeypatch.setattr(m, "s3", s3)
        monkeypatch.setattr(m, "BUCKET", BUCKET)

        yield m.lambda_handler, s3

    sys.modules.pop("lambda_ingest.handler", None)  # clean up after test


def test_handler_returns_200(handler):
    lambda_handler, _ = handler
    with patch("lambda_ingest.handler.fetch_data", return_value=SAMPLE_PAYLOAD):
        result = lambda_handler({}, None)
    assert result["statusCode"] == 200


def test_handler_returns_s3_key(handler):
    lambda_handler, _ = handler
    with patch("lambda_ingest.handler.fetch_data", return_value=SAMPLE_PAYLOAD):
        result = lambda_handler({}, None)
    assert result["key"].startswith("raw/year=")
    assert result["key"].endswith(".json")


def test_handler_writes_valid_json_to_s3(handler):
    lambda_handler, s3 = handler
    with patch("lambda_ingest.handler.fetch_data", return_value=SAMPLE_PAYLOAD):
        result = lambda_handler({}, None)

    obj = s3.get_object(Bucket=BUCKET, Key=result["key"])
    body = json.loads(obj["Body"].read())

    assert body["source"] == "open-meteo"
    assert "ingested_at" in body
    assert body["payload"]["current"]["temperature_2m"] == 21.5


def test_handler_object_content_type(handler):
    lambda_handler, s3 = handler
    with patch("lambda_ingest.handler.fetch_data", return_value=SAMPLE_PAYLOAD):
        result = lambda_handler({}, None)

    head = s3.head_object(Bucket=BUCKET, Key=result["key"])
    assert head["ContentType"] == "application/json"
