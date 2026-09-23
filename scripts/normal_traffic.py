"""Bounded localhost demo traffic exercising successful/rejected orders and Summary."""
import argparse
import json
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


def request(path, method="GET", body=None, rid=""):
    req = urllib.request.Request("http://127.0.0.1:8000" + path, method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Content-Type": "application/json", "X-Request-ID": rid})
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            return response.status, json.load(response)
    except urllib.error.HTTPError as error:
        return error.code, json.load(error)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, default=60)
    parser.add_argument("--interval", type=float, default=1)
    args = parser.parse_args()
    if not 1 <= args.count <= 100 or not 0.1 <= args.interval <= 10:
        parser.error("count must be 1..100 and interval 0.1..10 seconds")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    prefix = "normal-" + stamp
    folder = Path("docs/audit-evidence") / prefix
    folder.mkdir(parents=True, exist_ok=False)
    status, product = request("/api/products", "POST", {"name": prefix, "variant": "TEST", "price": 1, "stock_quantity": args.count + 1}, prefix + "-setup")
    assert status == 201, product
    payload = {"customer_reference": "DEMO-NONPERSONAL", "items": [{"product_id": product["id"], "quantity": 1}]}
    events, active = [], set()
    try:
        for n in range(1, args.count + 1):
            rid = f"{prefix}-{n:03d}"
            status, order = request("/api/orders", "POST", payload, rid)
            assert status == 201, order
            active.add(order["id"])
            time.sleep(args.interval)
            states = ("PACKED", "SHIPPED", "COMPLETED") if n % 2 else ("CANCELLED",)
            for state in states:
                code, result = request(f"/api/orders/{order['id']}/status", "PATCH", {"status": state}, rid)
                assert code == 200, result
            active.remove(order["id"])
            events.append({"request_id": rid, "order_id": order["id"], "terminal_status": states[-1]})
            if n % 10 == 0:
                code, result = request("/api/orders", "POST", {"customer_reference": "DEMO-NONPERSONAL", "items": [{"product_id": product["id"], "quantity": 10000}]}, rid + "-rejected")
                assert code == 400, result
                events.append({"request_id": rid + "-rejected", "status": code, "response": result})
                print(f"{n}/{args.count}: completed/cancelled orders and rejected-stock sample", flush=True)
    finally:
        for order_id in active:
            request(f"/api/orders/{order_id}/status", "PATCH", {"status": "CANCELLED"}, prefix + "-cleanup")
        # Only the dedicated fixture is restocked; cancelled/completed records remain.
        request(f"/api/products/{product['id']}/stock", "PATCH", {"stock_quantity": args.count + 1}, prefix + "-restock")
        (folder / "traffic.json").write_text(json.dumps({"prefix": prefix, "product_id": product["id"], "events": events,
            "finished_utc": datetime.now(timezone.utc).isoformat()}, indent=2))
    print(str(folder), flush=True)


if __name__ == "__main__":
    main()
