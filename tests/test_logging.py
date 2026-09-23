import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.logging_config import get_logger
from app.main import create_app


def json_records(capfd):
    return [json.loads(line) for line in capfd.readouterr().out.splitlines()]


@pytest.fixture(autouse=True)
def reset_logger_handler():
    logger = get_logger()
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)
        handler.close()
    yield


def test_request_id_is_returned_and_events_are_json(tmp_path: Path, capfd):
    with TestClient(create_app(tmp_path / "logging.db")) as client:
        response = client.post(
            "/api/products",
            headers={"X-Request-ID": "request-123"},
            json={"name": "Log Product", "variant": "Blue", "price": 10, "stock_quantity": 2},
        )

    assert response.headers["X-Request-ID"] == "request-123"
    records = json_records(capfd)
    assert any(record["message"] == "stock updated" and record["request_id"] == "request-123" for record in records)
    assert all({"timestamp", "service", "severity", "message", "request_id"}.issubset(record) for record in records)


def test_rejected_order_logs_warning_without_customer_reference(tmp_path: Path, capfd):
    with TestClient(create_app(tmp_path / "rejected.db")) as client:
        response = client.post(
            "/api/orders",
            json={"customer_reference": "PRIVATE-REFERENCE", "items": [{"product_id": 999, "quantity": 1}]},
        )

    assert response.status_code == 404
    records = json_records(capfd)
    rejected = next(record for record in records if record["message"] == "order rejected")
    assert rejected["severity"] == "WARNING"
    assert "PRIVATE-REFERENCE" not in json.dumps(rejected)


def test_invalid_request_logs_warning(tmp_path: Path, capfd):
    with TestClient(create_app(tmp_path / "invalid.db")) as client:
        response = client.post("/api/products", json={"name": "", "price": -1, "stock_quantity": -1})

    assert response.status_code == 422
    records = json_records(capfd)
    assert any(record["message"] == "invalid request" and record["severity"] == "WARNING" for record in records)


def test_unexpected_failure_is_measured_and_does_not_log_sensitive_exception(tmp_path, monkeypatch, capfd):
    from app.services import Store
    from tests.test_metrics import metric_value

    def broken_list(_):
        raise RuntimeError("SECRET-SHOULD-NOT-BE-LOGGED")

    with TestClient(create_app(tmp_path / "error.db"), raise_server_exceptions=False) as client:
        before = client.get("/metrics").text
        monkeypatch.setattr(Store, "list_products", broken_list)
        response = client.get("/api/products", headers={"X-Request-ID": "audit-error-test"})
        after = client.get("/metrics").text
    labels = {"method": "GET", "route": "/api/products", "status_code": "500"}
    assert response.status_code == 500
    assert metric_value(after, "http_requests_total", labels) == metric_value(before, "http_requests_total", labels) + 1
    duration_labels = {"method": "GET", "route": "/api/products"}
    assert metric_value(after, "http_request_duration_seconds_count", duration_labels) == metric_value(before, "http_request_duration_seconds_count", duration_labels) + 1
    records = json_records(capfd)
    event = next(r for r in records if r["message"] == "unexpected application error")
    assert event["severity"] == "ERROR" and event["request_id"] == "audit-error-test"
    assert event["status_code"] == 500
    assert "SECRET-SHOULD-NOT-BE-LOGGED" not in json.dumps(records)
