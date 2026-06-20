"""
Shared ingestion logic, reused unchanged across AWS Lambda, GCP Cloud
Functions, and Azure Functions.

Each cloud's compute wrapper imports `fetch_data` / `to_raw_record` /
`raw_object_key`, then handles the cloud-specific "write to object storage"
step.
"""

import json
import urllib.request
from datetime import UTC, datetime

# Example data source: Open-Meteo (no API key required), current weather
# for Paris. Replace with your chosen API.
DEFAULT_API_URL = (
    "https://api.open-meteo.com/v1/forecast"
    "?latitude=48.8566&longitude=2.3522"
    "&current=temperature_2m,wind_speed_10m,relative_humidity_2m"
)


def fetch_data(api_url: str = DEFAULT_API_URL) -> dict:
    """Fetch the raw JSON payload from the source API."""
    with urllib.request.urlopen(api_url, timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))


def to_raw_record(payload: dict) -> dict:
    """Wrap the raw payload with ingestion metadata before landing it."""
    return {
        "ingested_at": datetime.now(UTC).isoformat(),
        "source": "open-meteo",
        "payload": payload,
    }


def raw_object_key(prefix: str = "raw") -> str:
    """Date-partitioned key for the landing zone."""
    now = datetime.now(UTC)
    return (
        f"{prefix}/year={now.year}/month={now.month:02d}/day={now.day:02d}/{now.isoformat()}.json"
    )


if __name__ == "__main__":
    record = to_raw_record(fetch_data())
    print(json.dumps(record, indent=2))
