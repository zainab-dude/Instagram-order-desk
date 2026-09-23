"""Read-only capture of live service status, dashboard queries and log searches."""
import json
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs/audit-evidence"


def fetch(url, body=None):
    req = urllib.request.Request(url, data=json.dumps(body).encode() if body else None,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=15) as response:
            raw = response.read().decode()
            try:
                data = json.loads(raw)
            except ValueError:
                data = raw
            return {"status": response.status, "data": data}
    except urllib.error.HTTPError as error:
        return {"status": error.code, "error": error.read().decode()}


def main():
    OUT.mkdir(exist_ok=True)
    report = {"captured_utc": datetime.now(timezone.utc).isoformat(), "services": {}, "panel_queries": [], "logs": {}}
    for name, url in {
        "app": "http://localhost:8000/health", "home": "http://localhost:8000/",
        "prometheus": "http://localhost:9090/-/ready", "targets": "http://localhost:9090/api/v1/targets",
        "grafana": "http://localhost:3000/api/health", "grafana_dashboard": "http://localhost:3000/api/dashboards/uid/observable-orders",
        "elasticsearch": "http://localhost:9200/_cluster/health", "kibana": "http://localhost:5601/api/status",
        "data_views": "http://localhost:5601/api/data_views", "es_lifecycle": "http://localhost:9200/_data_stream/observable-orders-v3-*/_lifecycle",
    }.items():
        report["services"][name] = fetch(url)
    dashboard = json.loads((ROOT / "grafana/dashboards/observable-orders.json").read_text())
    for panel in dashboard["panels"]:
        for target in panel["targets"]:
            query = target["expr"].replace("$__rate_interval", "5m")
            result = fetch("http://localhost:9090/api/v1/query?" + urllib.parse.urlencode({"query": query}))
            report["panel_queries"].append({"panel": panel["title"], "query": query, "result": result})
    traffic = sorted(OUT.glob("normal-*/traffic.json"))[-1]
    prefix = json.loads(traffic.read_text())["prefix"]
    for name, query in {
        "latest_normal": {"prefix": {"request_id": prefix}},
        "latest_rejected": {"bool": {"filter": [{"prefix": {"request_id": prefix}}, {"match_phrase": {"message": "order rejected"}}]}},
        "original_proof": {"term": {"request_id": "pipeline-proof-20260922171843"}},
    }.items():
        report["logs"][name] = fetch("http://localhost:9200/observable-orders-v3-*/_search", {"size": 5, "track_total_hits": True, "query": query})
    report["normal_prefix"] = prefix
    (OUT / "live-observability.json").write_text(json.dumps(report, indent=2))
    for row in report["panel_queries"]:
        data = row["result"].get("data", {})
        print(row["panel"], data.get("status"), [(v["metric"], v["value"][1]) for v in data.get("data", {}).get("result", [])])
    for name, result in report["logs"].items():
        print(name, result.get("data", {}).get("hits", {}).get("total"))


if __name__ == "__main__":
    main()
