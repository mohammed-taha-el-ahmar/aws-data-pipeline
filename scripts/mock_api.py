"""
Local mock API server for testing frontend/index.html without AWS.

Usage:
    uv run python scripts/mock_api.py
    # then open http://localhost:8080 in your browser

The server handles two routes:
  GET /         → serves frontend/index.html with the placeholder API URL
                  replaced by http://localhost:8080/latest (no browser extension needed)
  GET /latest   → returns static JSON matching the query Lambda's output schema

The deployed version (S3) uses the real API Gateway URL injected by Terraform.
"""

import http.server
import json
from datetime import UTC, datetime
from pathlib import Path

PORT = 8080
PLACEHOLDER = "https://example.invalid/latest"
MOCK_URL = f"http://localhost:{PORT}/latest"
FRONTEND_HTML = Path(__file__).parent.parent / "frontend" / "index.html"

# Mirrors the real query Lambda response shape (shared/transform.py schema)
MOCK_DATA = {
    "ingested_at": datetime.now(UTC).isoformat(),
    "latitude": 48.86,
    "longitude": 2.36,
    "temperature_c": 21.5,
    "wind_speed_kmh": 6.2,
    "humidity_pct": 55.0,
}


class MockHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        if self.path in ("/", "/index.html"):
            self._serve_html()
        elif self.path in ("/latest", "/latest/"):
            self._serve_json()
        else:
            self.send_response(404)
            self.end_headers()

    def do_OPTIONS(self):  # noqa: N802
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.end_headers()

    def _serve_html(self):
        html = FRONTEND_HTML.read_text(encoding="utf-8").replace(PLACEHOLDER, MOCK_URL)
        body = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _serve_json(self):
        # Refresh timestamp on every request so the "Last updated" field advances
        MOCK_DATA["ingested_at"] = datetime.now(UTC).isoformat()
        body = json.dumps(MOCK_DATA).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        print(f"  {self.address_string()} {fmt % args}")


if __name__ == "__main__":
    server = http.server.HTTPServer(("", PORT), MockHandler)
    print(f"Mock server running — open http://localhost:{PORT} in your browser.")
    print("  GET /        → frontend/index.html (API URL auto-replaced)")
    print("  GET /latest  → mock weather JSON")
    print("Press Ctrl-C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
