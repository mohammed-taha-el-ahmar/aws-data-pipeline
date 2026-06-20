"""
Integration tests — require LocalStack running on localhost:4566.

Start LocalStack:
    docker compose -f docker-compose.localstack.yml up -d

These tests exercise the real S3 write path via a local AWS emulator.
fetch_data is still patched (avoids the external Open-Meteo call, keeps
tests deterministic).
"""

import json
from unittest.mock import patch

import boto3
import pytest

pytestmark = pytest.mark.integration

ENDPOINT = "http://localhost:4566"
REGION = "eu-west-3"
BUCKET = "data-pipeline-local"

SAMPLE_PAYLOAD = {
    "latitude": 48.86,
    "longitude": 2.36,
    "current": {
        "temperature_2m": 21.5,
        "wind_speed_10m": 6.2,
        "relative_humidity_2m": 55,
    },
}


@pytest.fixture(scope="module")
def s3():
    return boto3.client(
        "s3",
        endpoint_url=ENDPOINT,
        region_name=REGION,
        aws_access_key_id="test",
        aws_secret_access_key="test",
    )


@pytest.fixture(scope="module", autouse=True)
def bucket(s3):
    """Ensure the test bucket exists (init script may have already created it)."""
    try:
        s3.create_bucket(
            Bucket=BUCKET,
            CreateBucketConfiguration={"LocationConstraint": REGION},
        )
    except s3.exceptions.BucketAlreadyOwnedByYou:
        pass
    return BUCKET


@pytest.fixture()
def handler(monkeypatch, s3):
    """Patch the handler's module-level client and bucket to point at LocalStack."""
    import sys

    # Must set env var BEFORE importing — handler.py reads it at module level
    monkeypatch.setenv("DATA_LAKE_BUCKET", BUCKET)
    sys.modules.pop("lambda_ingest.handler", None)

    import lambda_ingest.handler as m

    monkeypatch.setattr(m, "s3", s3)
    monkeypatch.setattr(m, "BUCKET", BUCKET)
    return m.lambda_handler


def test_ingest_writes_object_to_localstack(handler, s3):
    with patch("lambda_ingest.handler.fetch_data", return_value=SAMPLE_PAYLOAD):
        result = handler({}, None)

    assert result["statusCode"] == 200
    key = result["key"]
    assert key.startswith("raw/")

    # Confirm the object actually landed in LocalStack S3
    obj = s3.get_object(Bucket=BUCKET, Key=key)
    body = json.loads(obj["Body"].read())

    assert body["source"] == "open-meteo"
    assert "ingested_at" in body
    assert body["payload"]["current"]["temperature_2m"] == 21.5


def test_ingest_key_is_date_partitioned(handler, s3):
    with patch("lambda_ingest.handler.fetch_data", return_value=SAMPLE_PAYLOAD):
        result = handler({}, None)

    key = result["key"]
    assert "/year=" in key
    assert "/month=" in key
    assert "/day=" in key


def test_multiple_ingestions_produce_distinct_keys(handler, s3):
    keys = []
    for _ in range(3):
        with patch("lambda_ingest.handler.fetch_data", return_value=SAMPLE_PAYLOAD):
            result = handler({}, None)
        keys.append(result["key"])

    # All three keys should be unique (ISO timestamp in the filename)
    assert len(set(keys)) == len(keys)


def test_raw_prefix_contains_objects(s3):
    """After ingest, raw/ should have at least one object."""
    response = s3.list_objects_v2(Bucket=BUCKET, Prefix="raw/")
    assert response["KeyCount"] > 0


def test_transform_record_matches_expected_schema():
    """
    End-to-end shape test: raw record → transform → expected warehouse row.
    Pure Python, included here so the integration suite covers the full shape.
    """
    from shared.ingest import to_raw_record
    from shared.transform import transform_record

    raw = to_raw_record(SAMPLE_PAYLOAD)
    row = transform_record(raw)

    assert row["latitude"] == 48.86
    assert row["temperature_c"] == 21.5
    assert row["wind_speed_kmh"] == 6.2
    assert row["humidity_pct"] == 55
