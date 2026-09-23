"""Verify saved evidence without creating any additional requests."""
import json
import sys
from pathlib import Path

root = Path(__file__).parent / "results" / sys.argv[1]


def read(mode, name):
    return json.loads((root / mode / name).read_text())


checks = {}
for mode, expected in (("request-id", 100), ("no-label", 1)):
    requests = read(mode, "requests.json")
    checks[mode + "_exact_workload"] = (
        len(requests) == 100
        and [r["request_id"] for r in requests] == [f"cardinality-{i:03d}" for i in range(1, 101)]
        and [r["response"]["accepted"] for r in requests] == list(range(1, 101))
    )
    rows = read(mode, "series.json")["data"]["result"]
    checks[mode + "_series_shape"] = len(rows) == expected and all(
        ("request_id" in row["metric"]) == (mode == "request-id") for row in rows)
    checks[mode + "_observed_count"] = float(read(mode, "count.json")["data"]["result"][0]["value"][1]) == expected
    checks[mode + "_total_requests"] = float(read(mode, "sum.json")["data"]["result"][0]["value"][1]) == 100
checks["old_instant_count_preserved"] = float(read("no-label", "historical-count.json")["data"]["result"][0]["value"][1]) == 100
checks["old_and_new_series_retained"] = len(read("no-label", "retained-series.json")["data"]) == 101
(root / "verification.json").write_text(json.dumps(checks, indent=2))
print(json.dumps(checks, indent=2))
assert all(checks.values())
