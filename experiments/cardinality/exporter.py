"""Isolated, bounded teaching exporter. Never imported by the orders app."""

import argparse
import json
import re
from http.server import BaseHTTPRequestHandler, HTTPServer

from prometheus_client import CollectorRegistry, Counter, CONTENT_TYPE_LATEST, generate_latest


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", required=True, choices=("request-id", "no-label"))
    args = parser.parse_args()
    registry = CollectorRegistry()  # Separate from the production/default registry.
    counter = Counter("demo_requests_total", "Accepted local demo requests.",
                      ["request_id"] if args.mode == "request-id" else [], registry=registry)
    accepted = set()

    class Handler(BaseHTTPRequestHandler):
        def reply(self, status, data, content_type="application/json"):
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            if self.path == "/metrics":
                self.reply(200, generate_latest(registry), CONTENT_TYPE_LATEST)
            elif self.path == "/health":
                self.reply(200, json.dumps({"mode": args.mode, "accepted": len(accepted)}).encode())
            else:
                self.reply(404, b'{}')

        def do_POST(self):
            if self.path != "/request":
                self.reply(404, b'{}')
                return
            rid = self.headers.get("X-Request-ID", "")
            if not re.fullmatch(r"cardinality-(?:0[0-9][0-9]|100)", rid) or rid == "cardinality-000":
                self.reply(400, b'{"error":"use cardinality-001 through cardinality-100"}')
                return
            if rid in accepted or len(accepted) >= 100:
                self.reply(409, b'{"error":"duplicate or 100-request cap reached"}')
                return
            accepted.add(rid)
            if args.mode == "request-id":
                counter.labels(request_id=rid).inc()
            else:
                counter.inc()
            self.reply(200, json.dumps({"mode": args.mode, "accepted": len(accepted)}).encode())

        def log_message(self, *_):
            pass

    HTTPServer(("0.0.0.0", 8010), Handler).serve_forever()


if __name__ == "__main__":
    main()
