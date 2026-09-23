"""Read-only verification of all three saved phases and fixture recovery."""

import hashlib
import json
import sys
import urllib.parse

from part_e_workload import APP, CONTROL, PROM, ROOT, request, save, utc


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def main():
    root = ROOT / "experiments/results" / sys.argv[1]
    summary = read(root / "summary.json")
    lock = read(root / "fault/prediction-lock.json")
    report = {"verified_at": utc(), "checks": {}, "scrapes": {}}
    checks = report["checks"]
    checks["predictions_unchanged"] = hashlib.sha256((root / "predictions.md").read_bytes()).hexdigest() == lock["sha256"]
    checks["control_disabled"] = CONTROL.read_text().strip() == "DISABLED"
    manifests = {phase: read(root / phase / "manifest.json") for phase in summary}
    checks["identical_workload_hash"] = len({m["workload_sha256"] for m in manifests.values()}) == 1
    checks["three_phases"] = set(summary) == {"normal", "fault", "recovery"}
    products = json.loads(request(APP + "/api/products")[1])
    report["fixtures"] = [p for p in products if p["id"] in {m["product_id"] for m in manifests.values()}]
    for phase, evidence in summary.items():
        checks[f"{phase}_successes"] = evidence["client"]["successes"] == 90 and evidence["client"]["errors"] == 0
        checks[f"{phase}_server_count"] = evidence["server_exact_count"] == 90
        expected = 18 if phase == "fault" else 0
        checks[f"{phase}_injections"] = evidence["injections"] == expected
        checks[f"{phase}_indexed_events"] = evidence["indexed_documents"] == 180 + expected and evidence["completed_logs"] == 90
        checks[f"{phase}_cleanup"] = evidence["cleanup_successes"] == evidence["cleanup_total"] == 91
        for name, query in {
            "count": 'count_over_time(up{job=~"fastapi-app|node-exporter"}[90s])',
            "minimum_up": 'min_over_time(up{job=~"fastapi-app|node-exporter"}[90s])',
        }.items():
            url = PROM + "/api/v1/query?" + urllib.parse.urlencode({"query": query, "time": manifests[phase]["end"]})
            response = json.loads(request(url)[1])
            report["scrapes"][f"{phase}_{name}"] = {"query": query, "response": response}
            values = [float(item["value"][1]) for item in response["data"]["result"]]
            checks[f"{phase}_{name}"] = len(values) == 2 and all(v >= 5 if name == "count" else v == 1 for v in values)
    expected_ids = [f"parte-{sys.argv[1]}-fault-{i:03d}" for i in range(5, 91, 5)]
    checks["exact_fifth_request_cadence"] = summary["fault"]["injection_request_ids"] == expected_ids
    checks["stock_restored"] = len(report["fixtures"]) == 3 and all(p["reserved_quantity"] == 0 and p["available_quantity"] == 91 for p in report["fixtures"])
    save(root / "verification.json", report)
    print(json.dumps(checks, indent=2))
    if not all(checks.values()):
        raise SystemExit("Verification has failures; inspect verification.json")


if __name__ == "__main__":
    main()
