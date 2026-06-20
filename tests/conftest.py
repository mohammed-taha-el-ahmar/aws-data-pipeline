"""
Shared pytest fixtures and markers.

Markers
-------
unit        - pure Python, no AWS, no Docker
integration - requires LocalStack (docker compose -f docker-compose.localstack.yml up -d)
"""

import boto3
import pytest
from moto import mock_aws

LOCALSTACK_ENDPOINT = "http://localhost:4566"
LOCALSTACK_REGION = "eu-west-3"
LOCALSTACK_BUCKET = "data-pipeline-local"


# ---------------------------------------------------------------------------
# Helper: check if LocalStack is reachable
# ---------------------------------------------------------------------------


def _localstack_running() -> bool:
    try:
        import requests

        r = requests.get(f"{LOCALSTACK_ENDPOINT}/_localstack/health", timeout=2)
        return r.status_code == 200
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Pytest marker: skip when LocalStack is not up
# ---------------------------------------------------------------------------


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "integration: requires LocalStack — run: "
        "docker compose -f docker-compose.localstack.yml up -d",
    )
    config.addinivalue_line("markers", "unit: pure unit test, no external deps")


def pytest_collection_modifyitems(config, items):
    if not _localstack_running():
        skip = pytest.mark.skip(
            reason="LocalStack not running — "
            "start with: docker compose -f docker-compose.localstack.yml up -d"
        )
        for item in items:
            if "integration" in item.keywords:
                item.add_marker(skip)


# ---------------------------------------------------------------------------
# Fixtures: moto (unit tests)
# ---------------------------------------------------------------------------


@pytest.fixture
def aws_env(monkeypatch):
    """Dummy AWS credentials so boto3 doesn't look for real ones."""
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_SECURITY_TOKEN", "testing")
    monkeypatch.setenv("AWS_SESSION_TOKEN", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", LOCALSTACK_REGION)


@pytest.fixture
def moto_s3(aws_env):
    """Moto-backed S3 client with a pre-created data-lake bucket."""
    with mock_aws():
        client = boto3.client("s3", region_name=LOCALSTACK_REGION)
        client.create_bucket(
            Bucket="test-data-lake",
            CreateBucketConfiguration={"LocationConstraint": LOCALSTACK_REGION},
        )
        yield client


# ---------------------------------------------------------------------------
# Fixtures: LocalStack (integration tests)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def ls_s3():
    """Real boto3 S3 client pointed at LocalStack."""
    return boto3.client(
        "s3",
        endpoint_url=LOCALSTACK_ENDPOINT,
        region_name=LOCALSTACK_REGION,
        aws_access_key_id="test",
        aws_secret_access_key="test",
    )


@pytest.fixture(scope="session", autouse=False)
def ls_bucket(ls_s3):
    """Ensure the local test bucket exists in LocalStack."""
    try:
        ls_s3.create_bucket(
            Bucket=LOCALSTACK_BUCKET,
            CreateBucketConfiguration={"LocationConstraint": LOCALSTACK_REGION},
        )
    except ls_s3.exceptions.BucketAlreadyOwnedByYou:
        pass
    return LOCALSTACK_BUCKET
