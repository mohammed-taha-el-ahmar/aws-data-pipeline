"""
Shared transform logic. Takes a raw landed record and produces a flat row
ready to load into a warehouse table.

Each cloud's transform wrapper:
  1. Reads the raw object from storage
  2. Calls `transform_record`
  3. Writes the resulting row into the warehouse
     (Redshift / BigQuery / Azure SQL)
"""

from typing import Any


def transform_record(raw: dict[str, Any]) -> dict[str, Any]:
    """Flatten one raw ingestion record into a warehouse-ready row."""
    payload = raw["payload"]
    current = payload.get("current", {})

    return {
        "ingested_at": raw["ingested_at"],
        "latitude": payload.get("latitude"),
        "longitude": payload.get("longitude"),
        "temperature_c": current.get("temperature_2m"),
        "wind_speed_kmh": current.get("wind_speed_10m"),
        "humidity_pct": current.get("relative_humidity_2m"),
    }


# Reference DDL — adapt syntax slightly per warehouse
# (Redshift / BigQuery / Azure SQL all accept variants of this).
WAREHOUSE_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS weather_observations (
    ingested_at      TIMESTAMP,
    latitude         FLOAT,
    longitude        FLOAT,
    temperature_c    FLOAT,
    wind_speed_kmh   FLOAT,
    humidity_pct     FLOAT
);
"""
