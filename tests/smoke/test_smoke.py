"""
Smoke tests — run in CI after the LocalStack service is healthy.

These are intentionally narrow: they verify that the critical path
(ingest → S3 write → readback → transform → expected schema) works
end-to-end against a real S3-compatible store (LocalStack), without any
mocking of the storage layer.

Marked with both `smoke` and `integration` so they run:
  - in CI (job: integration), after LocalStack is up
  - locally: uv run pytest tests/smoke -m smoke
  - skipped automatically if LocalStack is not reachable
"""

import json
import os
import sys
from unittest.mock import patch

import boto3
import pytest

pytestmark = [pytest.mark.smoke, pytest.mark.integration]

ENDPOINT = os.environ.get("LOCALSTACK_ENDPOINT", "http://localhost:4566")
REGION = "eu-west-3"
BUCKET = "data-pipeline-local"

FIXTURE_PAYLOAD = {
    "latitude": 48.86,
    "longitude": 2.36,
    "current": {
        "temperature_2m": 21.5,
        "wind_speed_10m": 6.2,
        "relative_humidity_2m": 55,
    },
}

EXPECTED_SCHEMA = {
    "ingested_at",
    "latitude",
    "longitude",
    "temperature_c",
    "wind_speed_kmh",
    "humidity_pct",
}


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────


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
def ensure_bucket(s3):
    try:
        s3.create_bucket(
            Bucket=BUCKET,
            CreateBucketConfiguration={"LocationConstraint": REGION},
        )
    except s3.exceptions.BucketAlreadyOwnedByYou:
        pass


@pytest.fixture()
def handler(monkeypatch, s3):
    """Lambda handler with its boto3 client pointed at LocalStack."""
    monkeypatch.setenv("DATA_LAKE_BUCKET", BUCKET)
    sys.modules.pop("lambda_ingest.handler", None)  # force fresh import

    import lambda_ingest.handler as m  # noqa: PLC0415

    monkeypatch.setattr(m, "s3", s3)
    monkeypatch.setattr(m, "BUCKET", BUCKET)

    yield m.lambda_handler

    sys.modules.pop("lambda_ingest.handler", None)


# ─────────────────────────────────────────────────────────────────────────────
# Smoke test 1 — ingest → S3 write
# ─────────────────────────────────────────────────────────────────────────────


def test_smoke_ingest_writes_to_s3(handler, s3):
    """Critical path: handler must write a JSON object to S3."""
    with patch("lambda_ingest.handler.fetch_data", return_value=FIXTURE_PAYLOAD):
        result = handler({}, None)

    assert result["statusCode"] == 200, f"unexpected status: {result}"

    key = result["key"]
    obj = s3.get_object(Bucket=BUCKET, Key=key)
    body = json.loads(obj["Body"].read())

    assert body["source"] == "open-meteo"
    assert "ingested_at" in body
    assert "payload" in body


# ─────────────────────────────────────────────────────────────────────────────
# Smoke test 2 — raw record → transform → warehouse schema
# ─────────────────────────────────────────────────────────────────────────────


def test_smoke_transform_output_schema(handler, s3):
    """
    Read back what was written to S3, run it through transform_record, and
    assert the output matches the expected warehouse schema.
    """
    from shared.transform import transform_record

    with patch("lambda_ingest.handler.fetch_data", return_value=FIXTURE_PAYLOAD):
        result = handler({}, None)

    obj = s3.get_object(Bucket=BUCKET, Key=result["key"])
    raw = json.loads(obj["Body"].read())

    row = transform_record(raw)

    assert set(row.keys()) == EXPECTED_SCHEMA, (
        f"Schema mismatch.\n  expected: {EXPECTED_SCHEMA}\n  got:      {set(row.keys())}"
    )
    assert row["temperature_c"] == FIXTURE_PAYLOAD["current"]["temperature_2m"]
    assert row["wind_speed_kmh"] == FIXTURE_PAYLOAD["current"]["wind_speed_10m"]
    assert row["humidity_pct"] == FIXTURE_PAYLOAD["current"]["relative_humidity_2m"]
    assert row["latitude"] == FIXTURE_PAYLOAD["latitude"]
    assert row["longitude"] == FIXTURE_PAYLOAD["longitude"]


# ─────────────────────────────────────────────────────────────────────────────
# Smoke test 3 — S3 key is date-partitioned (matches Glue crawler expectation)
# ─────────────────────────────────────────────────────────────────────────────


def test_smoke_s3_key_partitioned(handler, s3):
    """
    The Glue raw crawler expects raw/year=YYYY/month=MM/day=DD/<ts>.json.
    Verify the key layout is correct so the crawler will find the objects.
    """
    with patch("lambda_ingest.handler.fetch_data", return_value=FIXTURE_PAYLOAD):
        result = handler({}, None)

    key = result["key"]
    parts = key.split("/")
    assert parts[0] == "raw"
    assert parts[1].startswith("year=")
    assert parts[2].startswith("month=")
    assert parts[3].startswith("day=")
    assert parts[4].endswith(".json")


# ─────────────────────────────────────────────────────────────────────────────
# Smoke test 4 — S3 bucket is accessible and raw/ prefix has objects
# ─────────────────────────────────────────────────────────────────────────────


def test_smoke_s3_bucket_accessible(s3):
    """LocalStack S3 must be reachable and the data-lake bucket must exist."""
    response = s3.list_buckets()
    bucket_names = [b["Name"] for b in response["Buckets"]]
    assert BUCKET in bucket_names, f"Expected bucket '{BUCKET}' not found. Buckets: {bucket_names}"


def test_smoke_raw_prefix_has_objects_after_ingest(handler, s3):
    """After at least one ingest, raw/ must be non-empty."""
    with patch("lambda_ingest.handler.fetch_data", return_value=FIXTURE_PAYLOAD):
        handler({}, None)

    response = s3.list_objects_v2(Bucket=BUCKET, Prefix="raw/")
    assert response.get("KeyCount", 0) > 0, "raw/ prefix is empty after ingest"


# ─────────────────────────────────────────────────────────────────────────────
# Smoke test 5 — transform is idempotent (same input → same output)
# ─────────────────────────────────────────────────────────────────────────────


def test_smoke_transform_is_idempotent():
    """transform_record must be a pure function — same input always gives same output."""
    from shared.ingest import to_raw_record
    from shared.transform import transform_record

    raw = to_raw_record(FIXTURE_PAYLOAD)
    row_a = transform_record(raw)
    row_b = transform_record(raw)

    assert row_a == row_b
