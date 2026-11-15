"""A3 Part D failure/recovery run: load for 90 s, stop replica B at ~30 s, start it at ~60 s.

Usage (Envoy must already run `rr --health`):
  python scripts/failure_run.py --interface http --out results/d3-fail-http.json

While the load runs, Envoy's admin /clusters endpoint is polled every 0.5 s and every change of a
host's health is recorded. Writes results/<name>.events.json with the stop/start command times,
the health transitions, and the measured removal/recovery times; also saves Envoy's health-check
event log lines for the window to results/<name>.envoy-hc.log.
"""
import argparse
import json
import subprocess
import sys
import threading
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ADMIN = "http://localhost:9901/clusters?format=json"
CLUSTERS = ("http_cluster", "grpc_cluster")


def utc(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).isoformat(timespec="milliseconds")


def host_health() -> dict:
    with urllib.request.urlopen(ADMIN, timeout=2) as response:
        data = json.load(response)
    state = {}
    for cluster in data.get("cluster_statuses", []):
        if cluster["name"] not in CLUSTERS:
            continue
        for host in cluster.get("host_statuses", []):
            flags = {k: v for k, v in host.get("health_status", {}).items() if k != "eds_health_status" and v}
            name = host.get("hostname") or host["address"]["socket_address"]["address"]
            state[f"{cluster['name']}/{name}"] = "unhealthy:" + ",".join(sorted(flags)) if flags else "healthy"
    return state


class Watcher(threading.Thread):
    def __init__(self):
        super().__init__(daemon=True)
        self.transitions, self.stop_flag, self.last = [], threading.Event(), {}

    def run(self):
        while not self.stop_flag.is_set():
            now = time.time()
            try:
                state = host_health()
            except Exception as error:  # Envoy admin briefly unavailable
                state = {"admin": f"error:{type(error).__name__}"}
            for key, value in state.items():
                if self.last.get(key) != value:
                    self.transitions.append({"t": now, "utc": utc(now), "host": key, "state": value})
            self.last = state
            time.sleep(0.5)


def compose(*args) -> dict:
    begin = time.time()
    proc = subprocess.run(["docker", "compose", *args], cwd=ROOT, capture_output=True, text=True)
    end = time.time()
    return {"cmd": "docker compose " + " ".join(args), "begin_utc": utc(begin), "end_utc": utc(end),
            "begin": begin, "end": end, "exit_code": proc.returncode}


def first(transitions, host, predicate, after):
    for tr in transitions:
        if tr["host"] == host and tr["t"] >= after and predicate(tr["state"]):
            return tr
    return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--interface", choices=["http", "grpc"], required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--rate", type=float, default=20)
    parser.add_argument("--duration", type=float, default=90)
    parser.add_argument("--stop-at", type=float, default=30)
    parser.add_argument("--start-at", type=float, default=60)
    args = parser.parse_args()

    watcher = Watcher()
    watcher.start()
    time.sleep(1)
    launched = time.time()
    client = subprocess.Popen([sys.executable, str(ROOT / "scripts/lb_client.py"), "--interface", args.interface,
                               "--rate", str(args.rate), "--duration", str(args.duration), "--out", args.out], cwd=ROOT)
    time.sleep(max(0, launched + args.stop_at - time.time()))
    stop = compose("stop", "app-b", "grpc-b")
    print(f"stopped B: {stop['begin_utc']} -> {stop['end_utc']}", flush=True)
    time.sleep(max(0, launched + args.start_at - time.time()))
    start = compose("start", "app-b", "grpc-b")
    print(f"started B: {start['begin_utc']} -> {start['end_utc']}", flush=True)
    client.wait()
    deadline = time.time() + 30  # keep watching until B is healthy again in both clusters
    while time.time() < deadline and not all(watcher.last.get(f"{c}/{h}") == "healthy"
                                             for c, h in (("http_cluster", "app-b"), ("grpc_cluster", "grpc-b"))):
        time.sleep(0.5)
    watcher.stop_flag.set()
    watcher.join()

    measured = {}
    for cluster, host in (("http_cluster", "app-b"), ("grpc_cluster", "grpc-b")):
        key = f"{cluster}/{host}"
        down = first(watcher.transitions, key, lambda s: s.startswith("unhealthy"), stop["begin"])
        up = first(watcher.transitions, key, lambda s: s == "healthy", start["begin"])
        measured[key] = {
            "marked_unhealthy_utc": down and down["utc"],
            "removal_s_from_stop_cmd_begin": down and round(down["t"] - stop["begin"], 2),
            "removal_s_from_stop_cmd_end": down and round(down["t"] - stop["end"], 2),
            "marked_healthy_utc": up and up["utc"],
            "recovery_s_from_start_cmd_begin": up and round(up["t"] - start["begin"], 2),
            "recovery_s_from_start_cmd_end": up and round(up["t"] - start["end"], 2),
        }
    events = {"interface": args.interface, "poll_interval_s": 0.5,
              "health_check": {"interval_s": 2, "timeout_s": 1, "unhealthy_threshold": 3, "healthy_threshold": 2},
              "stop": stop, "start": start, "measured": measured, "transitions": watcher.transitions}
    out = Path(args.out)
    out.with_suffix(".events.json").write_text(json.dumps(events, indent=2))
    since = datetime.fromtimestamp(launched - 2, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    logs = subprocess.run(["docker", "logs", "--since", since, "observable-orders-envoy"],
                          capture_output=True, text=True, encoding="utf-8", errors="replace")
    hc_lines = [line for line in (logs.stdout + logs.stderr).splitlines() if "health_checker_type" in line]
    out.with_suffix(".envoy-hc.log").write_text("\n".join(hc_lines) + "\n", encoding="utf-8")
    print(json.dumps(measured, indent=1))


if __name__ == "__main__":
    main()
