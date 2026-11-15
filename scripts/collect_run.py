"""Collect Prometheus + Elasticsearch evidence for one lb_client run (A3).

Usage: python scripts/collect_run.py results/<name>.json

Writes:
  results/<name>.prometheus.json  every PromQL query with its raw response
  results/<name>.es.json          Elasticsearch queries + raw responses (Envoy events per replica)
  results/<name>.summary.json     per-replica comparison: Prometheus vs Envoy access logs vs client
Only standard library; Prometheus on localhost:9090, Elasticsearch on localhost:9200.
"""
import json
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

PROM = "http://localhost:9090/api/v1/"
ES = "http://localhost:9200/observable-orders-v3-*/"
SCRAPE_MARGIN = 12  # seconds after the run so the last 5 s scrape is in Prometheus


def http_json(url: str, body: dict | None = None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"} if data else {})
    with urllib.request.urlopen(req, timeout=30) as response:
        return json.load(response)


def ts(iso: str) -> float:
    return datetime.fromisoformat(iso).timestamp()


def prom_instant(query: str, at: float) -> dict:
    return http_json(PROM + "query?" + urllib.parse.urlencode({"query": query, "time": at}))


def prom_range(query: str, start: float, end: float, step: int = 5) -> dict:
    return http_json(PROM + "query_range?" + urllib.parse.urlencode(
        {"query": query, "start": start, "end": end, "step": step}))


def reset_aware_delta(values: list, range_start: float | None = None, step: int = 5) -> float:
    """Counter increase between first and last sample, adding back counter resets (replica restart).

    A series that first appears inside the window (a replica's first-ever call with that label set)
    started from 0, so its first sample counts in full.
    """
    total, prev = 0.0, None
    if range_start is not None and values and float(values[0][0]) > range_start + step:
        prev = 0.0
    for _, raw in values:
        v = float(raw)
        if prev is not None:
            total += v - prev if v >= prev else v
        prev = v
    return total


def by_label(response: dict, label: str, fn) -> dict:
    return {r["metric"].get(label, "-"): fn(r) for r in response["data"]["result"]}


def main():
    result_path = Path(sys.argv[1])
    client = json.loads(result_path.read_text())
    interface, prefix = client["interface"], client["request_id_prefix"]
    start, end = ts(client["start_utc"]), ts(client["end_utc"])
    wait = end + SCRAPE_MARGIN - time.time()
    if wait > 0:
        time.sleep(wait)
    window = int(end - start) + SCRAPE_MARGIN + 5      # seconds covered by [..] range selectors
    at = end + SCRAPE_MARGIN                           # evaluation time for instant queries
    run_seconds = end - start

    if interface == "http":
        sel = 'job="fastapi-app",route="/api/products",method="GET"'
        counter = f"http_requests_total{{{sel}}}"
        code_q = f"sum by (replica, status_code) (http_requests_total{{{sel}}})"
        hist = f"http_request_duration_seconds_bucket{{{sel}}}"
        dsum = f"http_request_duration_seconds_sum{{{sel}}}"
        active = "http_server_active_requests"
        code_label, cluster = "status_code", "http_cluster"
    else:
        sel = 'job="grpc-service",grpc_method="CreateOrder"'
        counter = f"grpc_server_handled_total{{{sel}}}"
        code_q = f"sum by (replica, grpc_code) (grpc_server_handled_total{{{sel}}})"
        hist = f"grpc_server_handling_seconds_bucket{{{sel}}}"
        dsum = f"grpc_server_handling_seconds_sum{{{sel}}}"
        active = f"grpc_server_in_flight_requests{{{sel}}}"
        code_label, cluster = "grpc_code", "grpc_cluster"

    count_q = f"sum by (replica) ({counter})"
    queries = {
        "count_range": (count_q, "range"),
        "codes_range": (code_q, "range"),
        "p50_server": (f"histogram_quantile(0.50, sum by (replica, le) (increase({hist}[{window}s])))", "instant"),
        "p95_server": (f"histogram_quantile(0.95, sum by (replica, le) (increase({hist}[{window}s])))", "instant"),
        "duration_sum_range": (f"sum by (replica) ({dsum})", "range"),
        "active_max": (f"max by (replica) (max_over_time({active}[{window}s]))", "instant"),
        "dashboard_share_pct_1m": (
            f"100 * sum by (replica) (rate({counter}[1m])) / ignoring(replica) group_left sum(rate({counter}[1m]))",
            "mid"),
        "envoy_rq_total_range": (f'envoy_cluster_upstream_rq_total{{envoy_cluster_name="{cluster}"}}', "range"),
        "envoy_rq_active_max": (f'max_over_time(envoy_cluster_upstream_rq_active{{envoy_cluster_name="{cluster}"}}[{window}s])', "instant"),
        "envoy_membership_healthy_range": (f'envoy_cluster_membership_healthy{{envoy_cluster_name="{cluster}"}}', "range"),
        "envoy_membership_total_range": (f'envoy_cluster_membership_total{{envoy_cluster_name="{cluster}"}}', "range"),
    }
    raw = {}
    r_start, r_end = start - 10, at
    for name, (query, kind) in queries.items():
        if kind == "range":
            response = prom_range(query, r_start, r_end)
            meta = {"start": r_start, "end": r_end, "step": 5}
        elif kind == "mid":
            response = prom_instant(query, start + run_seconds * 0.75)  # inside the run, like the dashboard
            meta = {"time": start + run_seconds * 0.75}
        else:
            response = prom_instant(query, at)
            meta = {"time": at}
        raw[name] = {"query": query, **meta, "response": response}

    counts = by_label(raw["count_range"]["response"], "replica", lambda r: reset_aware_delta(r["values"], r_start))
    codes = {}
    for r in raw["codes_range"]["response"]["data"]["result"]:
        delta = reset_aware_delta(r["values"], r_start)
        if delta:
            codes.setdefault(r["metric"]["replica"], {})[r["metric"][code_label]] = round(delta)
    dsums = by_label(raw["duration_sum_range"]["response"], "replica", lambda r: reset_aware_delta(r["values"], r_start))
    p50 = by_label(raw["p50_server"]["response"], "replica", lambda r: r["value"][1])
    p95 = by_label(raw["p95_server"]["response"], "replica", lambda r: r["value"][1])
    act = by_label(raw["active_max"]["response"], "replica", lambda r: float(r["value"][1]))
    share1m = by_label(raw["dashboard_share_pct_1m"]["response"], "replica", lambda r: round(float(r["value"][1]), 2))
    envoy_rq = sum(reset_aware_delta(r["values"]) for r in raw["envoy_rq_total_range"]["response"]["data"]["result"])

    # ---- Elasticsearch: Envoy access-log events and replica events for this run's request IDs ----
    def es_query(service_filter: dict) -> dict:
        return {"size": 0, "track_total_hits": True, "query": {"bool": {"filter": [
            {"prefix": {"request_id": prefix}}, service_filter]}},
            "aggs": {"by_replica": {"terms": {"field": "replica", "size": 10}},
                     "by_code": {"terms": {"field": "envoy_response_code", "size": 10}},
                     "by_grpc_status": {"terms": {"field": "envoy_grpc_status", "size": 10}},
                     "by_flags": {"terms": {"field": "envoy_response_flags", "size": 10}}}}

    envoy_q = es_query({"term": {"service.name": "envoy"}})
    app_q = es_query({"term": {"service.name": "instagram-order-desk"}})
    envoy_res, previous = None, -1
    for _ in range(40):  # wait for Filebeat to ship everything (count stable and == sent)
        envoy_res = http_json(ES + "_search", envoy_q)
        hits = envoy_res["hits"]["total"]["value"]
        if hits >= client["sent"] or (hits == previous and hits > 0 and time.time() > end + 60):
            break  # every request logged, or no change for 5 s and at least 60 s since the run ended
        previous = hits
        time.sleep(5)
    app_res = http_json(ES + "_search", app_q)
    es_counts = {b["key"]: b["doc_count"] for b in envoy_res["aggregations"]["by_replica"]["buckets"]}

    total_prom = sum(counts.values()) or 1
    total_es = sum(es_counts.values()) or 1
    client_counts = client.get("served_by_counts", {})
    total_client = sum(v for k, v in client_counts.items() if k in ("A", "B", "C")) or 1
    replicas = {}
    for r in "ABC":
        replicas[r] = {
            "prometheus_count": round(counts.get(r, 0)),
            "prometheus_share_pct": round(100 * counts.get(r, 0) / total_prom, 2),
            "envoy_log_count": es_counts.get(r, 0),
            "envoy_log_share_pct": round(100 * es_counts.get(r, 0) / total_es, 2),
            "client_served_by_count": client_counts.get(r, 0),
            "client_share_pct": round(100 * client_counts.get(r, 0) / total_client, 2),
            "server_p50_ms": None if p50.get(r) in (None, "NaN") else round(1000 * float(p50[r]), 1),
            "server_p95_ms": None if p95.get(r) in (None, "NaN") else round(1000 * float(p95[r]), 1),
            "avg_concurrency": round(dsums.get(r, 0) / run_seconds, 3),
            "max_active_sampled": act.get(r),
            "dashboard_share_pct_1m_at_75pct": share1m.get(r),
            "status_codes": codes.get(r, {}),
        }
    summary = {
        "run": client["run"], "interface": interface,
        "window_utc": [client["start_utc"], client["end_utc"]],
        "client": {k: client[k] for k in ("target_rate_rps", "actual_rate_rps", "sent", "successes", "failures",
                                          "failures_by_code", "error_rate_pct", "client_latency_ms")},
        "replicas": replicas,
        "envoy_upstream_rq_total_delta": round(envoy_rq),
        "envoy_log_events": envoy_res["hits"]["total"]["value"],
        "envoy_log_response_flags": {b["key"]: b["doc_count"] for b in envoy_res["aggregations"]["by_flags"]["buckets"]},
        "replica_log_events": {b["key"]: b["doc_count"] for b in app_res["aggregations"]["by_replica"]["buckets"]},
        "notes": "avg_concurrency = increase(duration_sum)/run seconds (Little's law, time-averaged in-flight); "
                 "max_active_sampled = max of the gauge at 5 s scrapes; server p50/p95 from histogram buckets over the run.",
    }
    stem = result_path.with_suffix("")
    Path(f"{stem}.prometheus.json").write_text(json.dumps(raw, indent=1))
    Path(f"{stem}.es.json").write_text(json.dumps({"index": "observable-orders-v3-*", "envoy_query": envoy_q,
                                                   "envoy_response": envoy_res, "replica_query": app_q,
                                                   "replica_response": app_res}, indent=1))
    Path(f"{stem}.summary.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps({r: {k: v[k] for k in ("prometheus_share_pct", "envoy_log_share_pct", "client_share_pct",
                                            "server_p95_ms", "avg_concurrency")} for r, v in replicas.items()}, indent=1))


if __name__ == "__main__":
    main()
