"""
AWS Lambda: query

Called by API Gateway HTTP API (GET /latest).
Uses the Redshift Data API to execute a Spectrum query against the
processed/ Parquet table and return the most recent weather observation
as JSON.

No VPC required, no JDBC driver — the Redshift Data API is a managed
REST endpoint that Redshift Serverless exposes natively via IAM.
"""

import json
import os
import time

import boto3

client = boto3.client("redshift-data")
WORKGROUP = os.environ["REDSHIFT_WORKGROUP"]
DATABASE = os.environ.get("REDSHIFT_DATABASE", "dev")

SQL = """
SELECT ingested_at, latitude, longitude,
       temperature_c, wind_speed_kmh, humidity_pct
FROM spectrum.processed
ORDER BY ingested_at DESC
LIMIT 1
"""

CORS_HEADERS = {
    "Content-Type": "application/json",
    "Access-Control-Allow-Origin": "*",
}


def _field_value(field: dict):
    """Extract the typed value from a Redshift Data API Field union object."""
    if field.get("isNull"):
        return None
    for key in ("doubleValue", "longValue", "stringValue", "booleanValue"):
        if key in field:
            return field[key]
    return None


def _wait_for_result(statement_id: str, timeout: int = 25) -> list:
    """Poll describe_statement until finished; return the Records rows."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        desc = client.describe_statement(Id=statement_id)
        status = desc["Status"]
        if status == "FINISHED":
            result = client.get_statement_result(Id=statement_id)
            return result.get("Records", [])
        if status in ("FAILED", "ABORTED"):
            raise RuntimeError(f"Redshift statement {status}: {desc.get('Error', '')}")
        time.sleep(1)
    raise TimeoutError(f"Redshift statement did not finish in {timeout}s")


def _error(status: int, message: str, detail: str = "") -> dict:
    body = {"error": message}
    if detail:
        body["detail"] = detail
    return {"statusCode": status, "headers": CORS_HEADERS, "body": json.dumps(body)}


def lambda_handler(event, context):
    try:
        resp = client.execute_statement(
            WorkgroupName=WORKGROUP,
            Database=DATABASE,
            Sql=SQL,
        )
        rows = _wait_for_result(resp["Id"])

    except (RuntimeError, TimeoutError) as exc:
        err = str(exc)
        # Schema not yet created
        if "does not exist" in err or "schema" in err.lower() and "not exist" in err.lower():
            return _error(
                503,
                "spectrum schema not ready — run CREATE EXTERNAL SCHEMA first "
                "(see terraform output spectrum_schema_sql)",
                err,
            )
        # Schema exists but the Lambda IAM user has no USAGE/SELECT grant
        if "permission denied" in err.lower():
            return _error(
                503,
                "permission denied on spectrum schema — run the GRANT SQL "
                "(see terraform output spectrum_grant_sql)",
                err,
            )
        return _error(500, "query failed", err)

    except Exception as exc:  # noqa: BLE001
        return _error(500, "unexpected error", str(exc))

    if not rows:
        return _error(
            404,
            "no processed data yet — trigger the Lambda then run the Glue workflow",
        )

    # Column order matches the SELECT above
    row = rows[0]
    data = {
        "ingested_at": _field_value(row[0]),
        "latitude": _field_value(row[1]),
        "longitude": _field_value(row[2]),
        "temperature_c": _field_value(row[3]),
        "wind_speed_kmh": _field_value(row[4]),
        "humidity_pct": _field_value(row[5]),
    }

    return {
        "statusCode": 200,
        "headers": CORS_HEADERS,
        "body": json.dumps(data),
    }
