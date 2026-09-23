"""Send exactly 100 requests, wait for actual scrapes, save raw evidence."""

import argparse
import json
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


def get(url, method="GET", rid=None):
    req = urllib.request.Request(url, method=method, headers={"X-Request-ID": rid} if rid else {})
    with urllib.request.urlopen(req, timeout=5) as response:
        return response.read().decode()


def query(expression, timestamp=None):
    params = {"query": expression}
    if timestamp is not None:
        params["time"] = timestamp
    return json.loads(get("http://127.0.0.1:9091/api/v1/query?" + urllib.parse.urlencode(params)))


def save(path, value):
    path.write_text(json.dumps(value, indent=2), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("request-id", "no-label"), required=True)
    parser.add_argument("--run", required=True)
    args = parser.parse_args()
    if not args.run.replace("-", "").isalnum():
        parser.error("run name must be alphanumeric/hyphens")
    root = Path(__file__).parent / "results" / args.run
    folder = root / args.mode
    folder.mkdir(parents=True, exist_ok=False)
    health = json.loads(get("http://127.0.0.1:8010/health"))
    assert health == {"mode": args.mode, "accepted": 0}, health
    transcript = []
    for n in range(1, 101):
        rid = f"cardinality-{n:03d}"
        response = json.loads(get("http://127.0.0.1:8010/request", "POST", rid))
        assert response["accepted"] == n
        transcript.append({"request_id": rid, "response": response})
    completed = datetime.now(timezone.utc)
    save(folder / "requests.json", transcript)
    (folder / "metrics.txt").write_text(get("http://127.0.0.1:8010/metrics"), encoding="utf-8")
    expected = 100 if args.mode == "request-id" else 1
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        targets = json.loads(get("http://127.0.0.1:9091/api/v1/targets"))
        active = targets["data"]["activeTargets"]
        count = query("count(demo_requests_total)")
        values = count.get("data", {}).get("result", [])
        scraped = active and active[0]["health"] == "up" and datetime.fromisoformat(active[0]["lastScrape"].replace("Z", "+00:00")) > completed
        if scraped and values and float(values[0]["value"][1]) == expected:
            break
        time.sleep(1)
    else:
        raise RuntimeError("Expected fresh scraped count not observed; do not claim success")
    stamp = values[0]["value"][0]
    save(folder / "count.json", count)
    save(folder / "targets.json", targets)
    save(folder / "sum.json", query("sum(demo_requests_total)", stamp))
    save(folder / "series.json", query("demo_requests_total", stamp))
    save(folder / "manifest.json", {"mode": args.mode, "requests": 100,
        "completed_utc": completed.isoformat(), "observed_at": stamp,
        "observed_utc": datetime.fromtimestamp(stamp, timezone.utc).isoformat(),
        "observed_count": expected, "query": "count(demo_requests_total)"})
    if args.mode == "no-label":
        first = json.loads((root / "request-id/manifest.json").read_text())
        save(folder / "historical-count.json", query("count(demo_requests_total)", first["observed_at"]))
        params = urllib.parse.urlencode({"match[]": "demo_requests_total", "start": first["observed_at"], "end": stamp})
        save(folder / "retained-series.json", json.loads(get("http://127.0.0.1:9091/api/v1/series?" + params)))
    print(json.dumps({"mode": args.mode, "requests": 100, "count": count, "targets": active}, indent=2))


if __name__ == "__main__":
    main()
