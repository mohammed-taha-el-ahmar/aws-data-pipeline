# Local Testing Guide

## Service coverage by tier

| Service | Unit tests (moto) | LocalStack Community | LocalStack Pro |
|---|---|---|---|
| S3 (raw landing) | ✅ | ✅ | ✅ |
| Lambda handler | ✅ | ✅ | ✅ |
| EventBridge schedule | ✅ (mocked) | ✅ | ✅ |
| Glue Data Catalog | ✅ (mocked) | ⚠️ partial | ✅ |
| Glue Crawlers | ✅ (mocked) | ❌ | ✅ |
| Glue ETL / Spark | ❌ (Spark runtime) | ❌ | ✅ |
| Redshift Serverless | ❌ | ❌ | ✅ |

**Practical recommendation:** use **moto unit tests** for all business logic
and **LocalStack Community** for the S3 + Lambda integration path. Real Glue
ETL (Spark) always needs a real Glue environment or LocalStack Pro.

---

## Tier 1 — Unit tests (moto, no Docker)

No AWS account, no Docker, no internet required.

### What's tested

- `shared/ingest.py` — `fetch_data` (urllib patched), `to_raw_record`,
  `raw_object_key`
- `shared/transform.py` — `transform_record` field mapping, missing-field
  handling, JSON serializability
- `lambda_ingest/handler.py` — S3 `put_object` call, response shape,
  `ContentType` header — S3 is fully mocked via moto

### Run

```bash
# Install dev deps (one-time)
uv sync --group dev

# Run all unit tests
uv run pytest tests/unit -v

# With line-by-line coverage
uv run pytest tests/unit \
  --cov=shared \
  --cov=lambda_ingest \
  --cov-report=term-missing
```

### Project layout after setup

```
tests/
├── conftest.py              # shared fixtures + LocalStack skip logic
├── unit/
│   ├── test_ingest.py       # shared/ingest.py
│   ├── test_transform.py    # shared/transform.py
│   └── test_handler.py      # lambda_ingest/handler.py (moto S3)
└── integration/
    └── test_s3_pipeline.py  # end-to-end ingest → S3 (LocalStack)
```

### Why moto for the handler?

`lambda_ingest/handler.py` reads `DATA_LAKE_BUCKET` from the environment at
module level. The test fixture:

1. Sets `DATA_LAKE_BUCKET` via `monkeypatch.setenv` **before** importing the
   module.
2. Pops the module from `sys.modules` to force a fresh import (avoids stale
   cached module from previous test runs).
3. Imports inside a `mock_aws()` context so the module-level
   `boto3.client("s3")` connects to moto.
4. Patches the module-level `s3` client reference to a moto-backed client
   with a pre-created bucket.

The patch target for `fetch_data` must be
`"lambda_ingest.handler.fetch_data"` — **not** `"shared.ingest.fetch_data"`.
The handler uses `from shared.ingest import fetch_data`, which creates a
local binding; patching the source module's attribute has no effect on the
already-bound name.

---

## Tier 2 — LocalStack integration tests (S3 + Lambda path)

Tests the **real S3 write path** with a local AWS emulator, without needing
an AWS account.

### Prerequisites

- Docker Desktop running
- `uv sync --group dev --group localstack` (installs `awscli-local`)

### Start LocalStack

```bash
docker compose -f docker-compose.localstack.yml up -d
```

The init script (`localstack/init/ready.sh`) runs automatically and creates
the `data-pipeline-local` S3 bucket. Check it's ready:

```bash
curl -s http://localhost:4566/_localstack/health | python -m json.tool
# "s3": "available" should appear in the output
```

### Run integration tests

```bash
uv run pytest tests/integration -v
```

If LocalStack is not running, `conftest.py` auto-skips all tests marked
`@pytest.mark.integration` — the unit tests are unaffected.

### Run everything at once

```bash
# Unit tests always run; integration tests run only if LocalStack is up
uv run pytest -v
```

### Inspect S3 via awslocal

```bash
# List all objects that landed after running the tests
awslocal s3 ls s3://data-pipeline-local/raw/ --recursive

# Download and inspect one
awslocal s3 cp \
  s3://data-pipeline-local/raw/year=2026/month=06/day=20/<timestamp>.json \
  /tmp/sample.json
cat /tmp/sample.json | python -m json.tool
```

### Manually invoke the handler against LocalStack S3

```bash
DATA_LAKE_BUCKET=data-pipeline-local \
  AWS_ACCESS_KEY_ID=test \
  AWS_SECRET_ACCESS_KEY=test \
  AWS_DEFAULT_REGION=eu-west-3 \
  uv run python -c "
import boto3, os
from unittest.mock import patch
from shared.ingest import fetch_data

# Point boto3 at LocalStack
import lambda_ingest.handler as m
m.s3 = boto3.client('s3', endpoint_url='http://localhost:4566',
                    region_name='eu-west-3',
                    aws_access_key_id='test',
                    aws_secret_access_key='test')
m.BUCKET = 'data-pipeline-local'

# Uncomment to use real Open-Meteo data instead of a fixture:
# result = m.lambda_handler({}, None)

# Or use fixture data:
FIXTURE = {'latitude': 48.86, 'longitude': 2.36,
           'current': {'temperature_2m': 21.5,
                       'wind_speed_10m': 6.2,
                       'relative_humidity_2m': 55}}
with patch('lambda_ingest.handler.fetch_data', return_value=FIXTURE):
    result = m.lambda_handler({}, None)

import json; print(json.dumps(result, indent=2))
"
```

---

## Tier 3 — Glue ETL (Spark) — cloud or LocalStack Pro only

The `glue/jobs/transform_job.py` script uses `awsglue` and `pyspark` — both
are only available inside a Glue runtime (or Glue Docker image / LocalStack
Pro). You cannot run it with a plain Python interpreter.

### Options for testing the Glue job locally

| Option | Cost | Effort | Notes |
|---|---|---|---|
| Test `shared/transform.py` directly | Free | Low | Covers the field-mapping logic without Spark |
| [Glue Docker image](https://aws.amazon.com/blogs/big-data/develop-and-test-aws-glue-version-4-0-jobs-locally-using-a-docker-container/) | Free | Medium | `amazon/aws-glue-libs:glue_libs_4.0.0_image_01` |
| LocalStack Pro | Paid (~$35/mo) | Low | Full Glue + Redshift Serverless emulation |
| Real AWS (small Glue dev endpoint) | ~$0.44/hr | Low | Most accurate, use `terraform apply` |

### Run the Glue job in the official Docker image

```bash
# Pull the image (~4 GB)
docker pull amazon/aws-glue-libs:glue_libs_4.0.0_image_01

# Run the script (adjust volume paths and args as needed)
docker run -it --rm \
  -v "$PWD:/home/glue_user/workspace" \
  -e AWS_ACCESS_KEY_ID=test \
  -e AWS_SECRET_ACCESS_KEY=test \
  -e AWS_DEFAULT_REGION=eu-west-3 \
  amazon/aws-glue-libs:glue_libs_4.0.0_image_01 \
  spark-submit \
    /home/glue_user/workspace/glue/jobs/transform_job.py \
    --JOB_NAME test \
    --SOURCE_DATABASE data_pipeline_lake \
    --SOURCE_TABLE raw \
    --TARGET_S3_PATH s3://data-pipeline-local/processed/
```

### Validate the transform logic without Spark

The field mapping is mirrored in `shared/transform.py` (`transform_record`).
The unit tests in `tests/unit/test_transform.py` give you fast feedback on
any mapping changes, and the Glue job's `select()` should be kept in sync
with it manually.

---

## Quick reference

```
No Docker needed (moto):
  uv sync --group dev
  uv run pytest tests/unit -v

With Docker + LocalStack (S3 integration):
  docker compose -f docker-compose.localstack.yml up -d
  uv sync --group dev --group localstack
  uv run pytest tests/integration -v

Everything at once:
  uv run pytest -v
```
