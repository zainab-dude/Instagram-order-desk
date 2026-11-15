"""A3 fixed-rate, open-loop load client for HTTP and gRPC through Envoy.

Sends are scheduled at fixed times (t0 + n/rate) and never wait for earlier responses.
No retries, no circuit breaker, 5 s timeout. Every request carries x-request-id = lb-<run>-<n>.

  HTTP: GET /api/products                       (read-only)
  gRPC: orders.v1.OrderService/CreateOrder      (ONE fixed idempotency key and body per run:
        the first call creates one order, every later call is an idempotent replay)

Examples:
  python scripts/lb_client.py --interface http --rate 20 --duration 60 --out results/c-rr-http.json
  python scripts/lb_client.py --interface grpc --rate 20 --duration 60 --out results/c-rr-grpc.json
"""
import argparse
import asyncio
import json
import math
import os
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

TIMEOUT = 5.0


def utc(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).isoformat(timespec="milliseconds")


def nearest_rank(values: list[float], pct: float):
    if not values:
        return None
    ordered = sorted(values)
    return round(ordered[max(1, math.ceil(pct / 100 * len(ordered))) - 1], 2)


async def run_http(args, schedule):
    import httpx

    url = f"http://{args.target or 'localhost:8000'}/api/products"
    limits = httpx.Limits(max_connections=500, max_keepalive_connections=100)
    async with httpx.AsyncClient(timeout=TIMEOUT, limits=limits) as client:  # httpx never retries requests

        async def one(n: int, rid: str) -> dict:
            started = time.time()
            t = time.perf_counter()
            try:
                response = await client.get(url, headers={"x-request-id": rid})
                outcome = str(response.status_code)
                ok = 200 <= response.status_code < 300
                served = response.headers.get("x-served-by", "-")
            except httpx.HTTPError as error:
                outcome, ok, served = type(error).__name__, False, "-"
            return {"n": n, "request_id": rid, "sent_at": started, "latency_ms": (time.perf_counter() - t) * 1000,
                    "outcome": outcome, "ok": ok, "served_by": served}

        return await schedule(one)


async def run_grpc(args, schedule):
    import grpc
    import app.grpc_gen.orders_pb2 as pb
    import app.grpc_gen.orders_pb2_grpc as pb_grpc

    product_id = int(os.getenv("GRPC_PRODUCT_ID", "14"))
    request = pb.CreateOrderRequest(
        customer_reference=f"LB-{args.run}",
        items=[pb.OrderItem(product_id=product_id, quantity=1)],
        idempotency_key=f"lb-{args.run}-key",
    )
    # ONE channel = one HTTP/2 connection to Envoy; retries disabled.
    async with grpc.aio.insecure_channel(args.target or "localhost:50051",
                                         options=[("grpc.enable_retries", 0)]) as channel:
        stub = pb_grpc.OrderServiceStub(channel)

        async def one(n: int, rid: str) -> dict:
            started = time.time()
            t = time.perf_counter()
            call = stub.CreateOrder(request, timeout=TIMEOUT, metadata=(("x-request-id", rid),))
            replayed = None
            try:
                response = await call
                outcome, ok, replayed = "OK", True, response.replayed
            except grpc.aio.AioRpcError as error:
                outcome, ok = error.code().name, False
            latency = (time.perf_counter() - t) * 1000
            try:
                served = dict(await call.initial_metadata() or ()).get("x-served-by", "-")
            except Exception:
                served = "-"
            return {"n": n, "request_id": rid, "sent_at": started, "latency_ms": latency,
                    "outcome": outcome, "ok": ok, "served_by": served, "replayed": replayed}

        return await schedule(one)


async def main_async(args):
    total = int(args.rate * args.duration)
    send_times: list[float] = []

    async def schedule(one):
        loop = asyncio.get_running_loop()
        t0 = loop.time() + 0.2
        tasks = []
        for n in range(1, total + 1):
            delay = t0 + (n - 1) / args.rate - loop.time()
            if delay > 0:
                await asyncio.sleep(delay)
            send_times.append(time.time())
            tasks.append(asyncio.create_task(one(n, f"lb-{args.run}-{n}")))
        return await asyncio.gather(*tasks)

    runner = run_http if args.interface == "http" else run_grpc
    results = await runner(args, schedule)
    return results, send_times


def summarise(args, results, send_times):
    sent = len(results)
    successes = sum(r["ok"] for r in results)
    failures = Counter(r["outcome"] for r in results if not r["ok"])
    window = send_times[-1] - send_times[0] if sent > 1 else 0
    latencies = [r["latency_ms"] for r in results]
    ok_latencies = [r["latency_ms"] for r in results if r["ok"]]
    served = Counter(r["served_by"] for r in results)
    known = sum(v for k, v in served.items() if k in "ABC" and k)
    timeline = defaultdict(lambda: Counter())
    for r in results:
        second = int(r["sent_at"] - send_times[0])
        timeline[second]["sent"] += 1
        timeline[second]["ok" if r["ok"] else "error"] += 1
        timeline[second][f"served_{r['served_by']}"] += 1
    summary = {
        "run": args.run,
        "interface": args.interface,
        "operation": "GET /api/products" if args.interface == "http" else "orders.v1.OrderService/CreateOrder (fixed idempotency key)",
        "target_rate_rps": args.rate,
        "duration_s": args.duration,
        "actual_rate_rps": round((sent - 1) / window, 3) if window else None,
        "sent": sent,
        "successes": successes,
        "failures": sum(failures.values()),
        "failures_by_code": dict(failures),
        "error_rate_pct": round(100 * sum(failures.values()) / sent, 3) if sent else None,
        "client_latency_ms": {"p50": nearest_rank(latencies, 50), "p95": nearest_rank(latencies, 95),
                              "max": nearest_rank(latencies, 100), "method": "nearest rank, all requests"},
        "client_latency_success_ms": {"p50": nearest_rank(ok_latencies, 50), "p95": nearest_rank(ok_latencies, 95),
                                      "max": nearest_rank(ok_latencies, 100)},
        "served_by_counts": dict(sorted(served.items())),
        "served_by_share_pct": {k: round(100 * served.get(k, 0) / known, 2) for k in "ABC"} if known else {},
        "start_utc": utc(send_times[0]) if send_times else None,
        "end_utc": utc(max(r["sent_at"] + r["latency_ms"] / 1000 for r in results)) if results else None,
        "last_send_utc": utc(send_times[-1]) if send_times else None,
        "request_id_prefix": f"lb-{args.run}-",
        "settings": {"timeout_s": TIMEOUT, "retries": 0, "circuit_breaker": "none", "open_loop": True},
    }
    if args.interface == "grpc":
        summary["idempotency"] = {"key": f"lb-{args.run}-key",
                                  "created": sum(r.get("replayed") is False for r in results),
                                  "replayed": sum(r.get("replayed") is True for r in results)}
    summary["timeline_per_second"] = {str(k): dict(v) for k, v in sorted(timeline.items())}
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--interface", choices=["http", "grpc"], required=True)
    parser.add_argument("--rate", type=float, default=20.0, help="requests per second (default 20)")
    parser.add_argument("--duration", type=float, default=60.0, help="seconds (default 60)")
    parser.add_argument("--out", required=True, help="results/<name>.json")
    parser.add_argument("--run", help="run name used in request IDs (default: output file stem + time)")
    parser.add_argument("--target", help="override host:port (default localhost:8000 / localhost:50051)")
    args = parser.parse_args()
    args.run = args.run or f"{Path(args.out).stem}-{datetime.now(timezone.utc):%H%M%S}"
    results, send_times = asyncio.run(main_async(args))
    summary = summarise(args, results, send_times)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    requests_path = out.with_suffix(".requests.json")
    requests_path.write_text(json.dumps(
        [{**r, "sent_at": utc(r["sent_at"]), "latency_ms": round(r["latency_ms"], 2)} for r in results]), encoding="utf-8")
    brief = {k: summary[k] for k in ("run", "interface", "target_rate_rps", "actual_rate_rps", "sent", "successes",
                                     "failures", "failures_by_code", "client_latency_ms", "served_by_share_pct")}
    print(json.dumps(brief, indent=2))


if __name__ == "__main__":
    main()
