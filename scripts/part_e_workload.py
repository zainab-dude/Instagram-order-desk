"""Repeatable localhost-only Part E workload and measurements (standard library)."""

import argparse
import hashlib
import json
import math
import statistics
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTROL = ROOT / "experiments/control/latency.txt"
APP = "http://127.0.0.1:8000"
PROM = "http://127.0.0.1:9090"
ES = "http://127.0.0.1:9200"
COUNT = 45
INTERVAL = 2.0
LABELS = 'method="POST",route="/api/orders"'
QUERIES = {
    "mean_seconds": f'sum(increase(http_request_duration_seconds_sum{{{LABELS}}}[120s])) / sum(increase(http_request_duration_seconds_count{{{LABELS}}}[120s]))',
    "p95_seconds": f'histogram_quantile(0.95, sum by (le) (increase(http_request_duration_seconds_bucket{{{LABELS}}}[120s])))',
    "requests_per_second": f'sum(rate(http_requests_total{{{LABELS}}}[120s]))',
    "error_percent": f'100 * (sum(increase(http_requests_total{{{LABELS},status_code=~"4..|5.."}}[120s])) or vector(0)) / clamp_min(sum(increase(http_requests_total{{{LABELS}}}[120s])), 1)',
    "process_cpu_cores": 'rate(process_cpu_seconds_total{job="fastapi-app"}[120s])',
    "node_cpu_percent": '100 * (1 - avg(rate(node_cpu_seconds_total{job="node-exporter",mode="idle"}[120s])))',
    "scrape_up": 'up{job=~"fastapi-app|node-exporter"}',
}


def utc(epoch=None):
    return datetime.fromtimestamp(epoch or time.time(), timezone.utc).isoformat()


def request(url, method="GET", payload=None, request_id=None, headers_extra=None):
    headers = {}
    data = None
    if payload is not None:
        data = json.dumps(payload).encode()
        headers["Content-Type"] = "application/json"
    if request_id:
        headers["X-Request-ID"] = request_id
    if headers_extra:
        headers.update(headers_extra)
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            return response.status, response.read().decode()
    except urllib.error.HTTPError as error:
        return error.code, error.read().decode()

def save(path, value):
    path.write_text(json.dumps(value, indent=2), encoding="utf-8")


def pause_until(deadline):
    # Short sleeps let Ctrl+C interrupt; progress messages come from each phase.
    while time.monotonic() < deadline:
        time.sleep(max(0, min(0.25, deadline - time.monotonic())))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", choices=["normal", "fault", "recovery"], required=True)
    parser.add_argument("--run", required=True, help="Evidence directory name, shared by all phases")
    parser.add_argument("--ack-test-data", action="store_true", required=True)
    args = parser.parse_args()
    if not args.run.replace("-", "").replace("_", "").isalnum():
        parser.error("--run must contain only letters, numbers, hyphens or underscores")
    run_dir = ROOT / "experiments/results" / args.run
    folder = run_dir / args.phase
    folder.mkdir(parents=True, exist_ok=False)  # Never overwrite recorded results.
    predictions = run_dir / "predictions.md"
    if args.phase == "fault" and not predictions.exists():
        parser.error("Freeze predictions.md in the run directory before enabling the fault")
    if args.phase == "fault":
        save(folder / "prediction-lock.json", {
            "sha256": hashlib.sha256(predictions.read_bytes()).hexdigest(),
            "locked_at": utc(),
        })
    CONTROL.write_text("DISABLED\n", encoding="utf-8")
    orders = []
    results = []
    product_id = None
    try:
        status, body = request(APP + "/api/products", "POST", {
            "name": f"PART-E-{args.run}-{args.phase}", "variant": "TEST-ONLY",
            "price": 1, "stock_quantity": COUNT + 1,
        })
        if status != 201:
            raise RuntimeError(f"Fixture creation failed: {status} {body}")
        product_id = json.loads(body)["id"]
        payload = {"customer_reference": "PART-E-TEST", "items": [{"product_id": product_id, "quantity": 1}]}
        # Initialize route series before the measured window. Warmup is identical.
        status, body = request(APP + "/api/orders", "POST", payload, f"parte-{args.run}-{args.phase}-warmup")
        if status != 201:
            raise RuntimeError(f"Warmup failed: {status} {body}")
        warmup_id = json.loads(body)["id"]
        orders.append(warmup_id)
        print(f"{args.phase}: fault OFF; warmup complete; waiting 35s for scrapes", flush=True)
        pause_until(time.monotonic() + 35)
        (folder / "metrics-before.txt").write_text(request(APP + "/metrics")[1], encoding="utf-8")
        if args.phase == "fault":
            CONTROL.write_text("ENABLE_500MS_EVERY_5TH\n", encoding="utf-8")
        start = time.time()
        clock_start = time.monotonic()
        manifest = {
            "phase": args.phase, "run": args.run, "start": start, "start_utc": utc(start),
            "count": COUNT, "interval_seconds": INTERVAL, "product_id": product_id,
            "payload": payload, "fault_enabled": args.phase == "fault",
            "workload_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        }
        save(folder / "manifest.json", manifest)
        for sequence in range(1, COUNT + 1):
            scheduled = clock_start + (sequence - 1) * INTERVAL
            pause_until(scheduled)
            started = time.perf_counter()
            rid = f"parte-{args.run}-{args.phase}-{sequence:03d}"
            try:
                status, body = request(
                    APP + "/api/orders",
                    "POST",
                    payload,
                    request_id=rid,
                    headers_extra={"Idempotency-Key": rid}
                )
            except (OSError, urllib.error.URLError) as error:
                status, body = 0, str(error)
            latency = time.perf_counter() - started
            row = {"sequence": sequence, "request_id": rid, "status": status,
                   "latency_seconds": latency, "schedule_lag_seconds": started - scheduled,
                   "completed_utc": utc()}
            if status == 201:
                row["order_id"] = json.loads(body)["id"]
                orders.append(row["order_id"])
            else:
                row["error"] = body
            results.append(row)
            save(folder / "requests.json", results)
            if sequence % 15 == 0:
                print(f"{args.phase}: {sequence}/{COUNT}, latest {latency*1000:.1f} ms, HTTP {status}", flush=True)
        pause_until(clock_start + COUNT * INTERVAL)
        end = time.time()
        CONTROL.write_text("DISABLED\n", encoding="utf-8")
        (folder / "metrics-after.txt").write_text(request(APP + "/metrics")[1], encoding="utf-8")
        # Include a 15s margin on each side; wait for the ending sample to be scraped.
        evaluation = end + 15
        manifest.update(end=end, end_utc=utc(end), query_time=evaluation,
                        query_time_utc=utc(evaluation), query_window_start_utc=utc(evaluation - 120))
        save(folder / "manifest.json", manifest)
        latencies = sorted(row["latency_seconds"] for row in results)
        save(folder / "client-summary.json", {
            "count": len(results), "successes": sum(r["status"] == 201 for r in results),
            "errors": sum(r["status"] != 201 for r in results),
            "mean_ms": statistics.mean(latencies) * 1000,
            "p95_ms": latencies[math.ceil(0.95 * len(latencies)) - 1] * 1000,
            "max_ms": max(latencies) * 1000,
            "requests_per_second": len(results) / (end - start),
            "max_schedule_lag_ms": max(r["schedule_lag_seconds"] for r in results) * 1000,
        })
        print(f"{args.phase}: workload complete; fault OFF; waiting 35s for final scrapes/log shipping", flush=True)
        pause_until(time.monotonic() + 35)
        prometheus = {}
        for name, query in QUERIES.items():
            url = PROM + "/api/v1/query?" + urllib.parse.urlencode({"query": query, "time": evaluation})
            prometheus[name] = {"query": query, "response": json.loads(request(url)[1])}
        save(folder / "prometheus.json", prometheus)
        save(folder / "targets.json", json.loads(request(PROM + "/api/v1/targets")[1]))
        log_query = {"size": 500, "track_total_hits": True, "sort": [{"@timestamp": "asc"}],
                     "query": {"bool": {"filter": [
                         {"prefix": {"request_id": f"parte-{args.run}-{args.phase}-"}},
                         {"range": {"@timestamp": {"gte": utc(start), "lte": utc(end)}}}
                     ]}}}
        save(folder / "elasticsearch-query.json", log_query)
        status, body = request(ES + "/observable-orders-v3-*/_search", "POST", log_query)
        save(folder / "elasticsearch.json", {"http_status": status, "response": json.loads(body)})
        print(json.dumps(json.loads((folder / "client-summary.json").read_text()), indent=2), flush=True)
    finally:
        CONTROL.write_text("DISABLED\n", encoding="utf-8")
        # Cancel only orders created by this script; never delete user data.
        cleanup = []
        for order_id in orders:
            try:
                status, body = request(APP + f"/api/orders/{order_id}/status", "PATCH", {"status": "CANCELLED"})
                cleanup.append({"order_id": order_id, "status": status})
            except Exception as error:
                cleanup.append({"order_id": order_id, "error": str(error)})
        save(folder / "cleanup.json", cleanup)
        print(f"{args.phase}: fault OFF; cleanup recorded for {len(orders)} test orders", flush=True)


if __name__ == "__main__":
    main()
