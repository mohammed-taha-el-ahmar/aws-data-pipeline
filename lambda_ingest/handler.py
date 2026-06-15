"""
AWS Lambda: ingest

Triggered hourly by EventBridge. Fetches data via shared.ingest and writes
the raw record to the S3 landing zone under raw/.
"""

import json
import os

import boto3

from shared.ingest import fetch_data, raw_object_key, to_raw_record

s3 = boto3.client("s3")
BUCKET = os.environ["DATA_LAKE_BUCKET"]


def lambda_handler(event, context):
    raw = fetch_data()
    record = to_raw_record(raw)
    key = raw_object_key()

    s3.put_object(
        Bucket=BUCKET,
        Key=key,
        Body=json.dumps(record).encode("utf-8"),
        ContentType="application/json",
    )

    return {"statusCode": 200, "key": key}
