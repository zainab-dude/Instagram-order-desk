"""Summarize saved evidence without issuing traffic or editing predictions."""

import json
import sys
from pathlib import Path

from prometheus_client.parser import text_string_to_metric_families


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def metric(path, name):
    total = 0
    for family in text_string_to_metric_families(path.read_text(encoding="utf-8")):
        for sample in family.samples:
            if (sample.name == name and sample.labels.get("method") == "POST"
                    and sample.labels.get("route") == "/api/orders"):
                total += sample.value
    return total


def main():
    root = Path(__file__).resolve().parents[1] / "experiments/results" / sys.argv[1]
    summary = {}
    for phase in ("normal", "fault", "recovery"):
        folder = root / phase
        if not (folder / "cleanup.json").exists():
            continue
        client = read(folder / "client-summary.json")
        before, after = folder / "metrics-before.txt", folder / "metrics-after.txt"
        count = metric(after, "http_request_duration_seconds_count") - metric(before, "http_request_duration_seconds_count")
        duration = metric(after, "http_request_duration_seconds_sum") - metric(before, "http_request_duration_seconds_sum")
        sources = [hit["_source"] for hit in read(folder / "elasticsearch.json")["response"]["hits"]["hits"]]
        events = []
        for source in sources:
            try:
                events.append(json.loads(source["message"]))
            except (ValueError, TypeError):
                events.append(source)
        injections = [event for event in events if event.get("message") == "test-only order latency injected"]
        completed = [event for event in events if event.get("message") == "request completed"]
        cleanup = read(folder / "cleanup.json")
        prom = read(folder / "prometheus.json")
        summary[phase] = {
            "client": client,
            "server_exact_count": count,
            "server_exact_mean_ms": duration / count * 1000 if count else None,
            "prometheus": {name: item["response"].get("data", {}).get("result", []) for name, item in prom.items()},
            "indexed_documents": len(sources),
            "injections": len(injections),
            "injection_request_ids": [event["request_id"] for event in injections],
            "completed_logs": len(completed),
            "cleanup_successes": sum(item.get("status") == 200 for item in cleanup),
            "cleanup_total": len(cleanup),
        }
    (root / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
