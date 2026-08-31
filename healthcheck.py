#!/usr/bin/env python3
"""Healthcheck endpoint for Docker HEALTHCHECK.

Starts a tiny HTTP server on port 8080 that responds to GET /health
with 200 OK. Useful for Docker HEALTHCHECK and monitoring.
"""
import http.server
import json
import sys

class HealthHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/health":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "ok"}).encode())
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        pass  # suppress request logs

if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8080
    server = http.server.HTTPServer(("0.0.0.0", port), HealthHandler)
    print(f"Healthcheck listening on :{port}")
    server.serve_forever()
