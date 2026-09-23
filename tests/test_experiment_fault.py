import asyncio
import os
import time
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

from app.experiment_fault import OrderLatencyFault
from app.main import create_app


def test_fault_requires_startup_opt_in_even_with_enabled_file(tmp_path, monkeypatch):
    control = tmp_path / "latency.txt"
    control.write_text(OrderLatencyFault.TOKEN)
    monkeypatch.setattr(OrderLatencyFault, "CONTROL_FILE", control)
    monkeypatch.delenv("PART_E_TEST_MODE", raising=False)
    sleep = AsyncMock()
    monkeypatch.setattr("app.experiment_fault.asyncio.sleep", sleep)
    fault = OrderLatencyFault()
    for _ in range(10):
        asyncio.run(fault.before_request("POST", "/api/orders"))
    sleep.assert_not_awaited()


def test_cadence_route_scope_and_disable(tmp_path, monkeypatch):
    monkeypatch.setenv("PART_E_TEST_MODE", "controlled-local-only")
    control = tmp_path / "latency.txt"
    monkeypatch.setattr(OrderLatencyFault, "CONTROL_FILE", control)
    sleep = AsyncMock()
    monkeypatch.setattr("app.experiment_fault.asyncio.sleep", sleep)
    fault = OrderLatencyFault()
    asyncio.run(fault.before_request("POST", "/api/orders"))  # Missing = off.
    control.write_text(OrderLatencyFault.TOKEN)
    for i in range(1, 11):
        asyncio.run(fault.before_request("GET", "/api/orders"))
        asyncio.run(fault.before_request("POST", "/api/products"))
        asyncio.run(fault.before_request("POST", "/api/orders"))
        assert sleep.await_count == i // 5
    assert all(call.args == (0.5,) for call in sleep.await_args_list)
    control.write_text("DISABLED")
    for _ in range(10):
        asyncio.run(fault.before_request("POST", "/api/orders"))
    assert sleep.await_count == 2
    assert fault.sequence == 0
    control.write_text(OrderLatencyFault.TOKEN)
    expired = time.time() - 301
    os.utime(control, (expired, expired))
    for _ in range(5):
        asyncio.run(fault.before_request("POST", "/api/orders"))
    assert sleep.await_count == 2


def test_real_delay_is_in_http_histogram_and_order_still_succeeds(tmp_path, monkeypatch):
    from tests.test_metrics import metric_value

    monkeypatch.setenv("PART_E_TEST_MODE", "controlled-local-only")
    control = tmp_path / "latency.txt"
    control.write_text(OrderLatencyFault.TOKEN)
    monkeypatch.setattr(OrderLatencyFault, "CONTROL_FILE", control)
    labels = {"method": "POST", "route": "/api/orders"}
    with TestClient(create_app(tmp_path / "orders.db")) as client:
        product = client.post("/api/products", json={"name": "Fault Test", "price": 1, "stock_quantity": 5}).json()
        before = metric_value(client.get("/metrics").text, "http_request_duration_seconds_sum", labels)
        for _ in range(5):
            response = client.post("/api/orders", json={"customer_reference": "TEST", "items": [{"product_id": product["id"], "quantity": 1}]})
            assert response.status_code == 201
        after = metric_value(client.get("/metrics").text, "http_request_duration_seconds_sum", labels)
        assert after - before >= 0.5
