"""Build the A3 results table from results/*.summary.json (+ failure .events.json).

Usage: python scripts/summarize_results.py   ->  results/summary-table.md and results/all-runs.json
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results"
RUNS = [
    ("b-aonly-http", "A only", "none"), ("b-aonly-grpc", "A only", "none"),
    ("c-rr-http", "Round robin 1:1:1", "none"), ("c-rr-grpc", "Round robin 1:1:1", "none"),
    ("d1-weighted-http", "Weighted RR 2:1:1", "none"), ("d1-weighted-grpc", "Weighted RR 2:1:1", "none"),
    ("d2-rr-delayB-http", "Round robin 1:1:1", "B +200 ms"), ("d2-rr-delayB-grpc", "Round robin 1:1:1", "B +200 ms"),
    ("d2-least-delayB-http", "Least request (choice 3)", "B +200 ms"),
    ("d2-least-delayB-grpc", "Least request (choice 3)", "B +200 ms"),
    ("d3-fail-http", "RR + active HC", "B stopped ~30-60 s"), ("d3-fail-grpc", "RR + active HC", "B stopped ~30-60 s"),
]


def fmt_shares(rep, key):
    return " / ".join(f"{rep[r][key]:.1f}" for r in "ABC")


def main():
    rows, everything = [], {}
    for name, policy, fault in RUNS:
        path = RESULTS / f"{name}.summary.json"
        if not path.exists():
            continue
        s = json.loads(path.read_text())
        c, rep = s["client"], s["replicas"]
        events = RESULTS / f"{name}.events.json"
        extra = json.loads(events.read_text())["measured"] if events.exists() else None
        everything[name] = {"policy": policy, "fault": fault, **s, "failure_timing": extra}
        rows.append(
            f"| {name} | {policy}; {fault} | {c['target_rate_rps']:g} / {c['actual_rate_rps']} | "
            f"{fmt_shares(rep, 'prometheus_share_pct')} | {fmt_shares(rep, 'envoy_log_share_pct')} | "
            f"{c['client_latency_ms']['p95']} | {c['error_rate_pct']}% ({c['failures']}/{c['sent']}) | "
            f"{' / '.join(str(rep[r]['server_p95_ms']) for r in 'ABC')} | "
            f"{' / '.join(format(rep[r]['avg_concurrency'], '.2f') for r in 'ABC')} |")
    header = ("| Run / interface | Policy and fault | Target / actual rps | A/B/C share % (Prometheus) | "
              "A/B/C share % (Envoy logs) | Client p95 ms | Error rate | Server p95 ms A/B/C | Avg in-flight A/B/C |\n"
              "|---|---|---|---|---|---|---|---|---|")
    table = header + "\n" + "\n".join(rows) + "\n"
    (RESULTS / "summary-table.md").write_text(table, encoding="utf-8")
    (RESULTS / "all-runs.json").write_text(json.dumps(everything, indent=2), encoding="utf-8")
    print(table)


if __name__ == "__main__":
    main()
