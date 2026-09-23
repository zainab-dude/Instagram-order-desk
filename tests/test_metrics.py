from pathlib import Path

from fastapi.testclient import TestClient
from prometheus_client.parser import text_string_to_metric_families

from app.main import create_app


def metric_value(text: str, name: str, labels: dict[str, str] | None = None) -> float:
    labels = labels or {}
    for family in text_string_to_metric_families(text):
        for sample in family.samples:
            if sample.name == name and all(sample.labels.get(key) == value for key, value in labels.items()):
                return sample.value
    return 0.0


def test_metrics_track_http_and_business_workflows(tmp_path: Path):
    with TestClient(create_app(tmp_path / "metrics.db")) as client:
        initial = client.get("/metrics").text
        assert metric_value(initial, "pending_orders") == 0

        product_response = client.post(
            "/api/products",
            json={"name": "Metric Product", "variant": "Blue", "price": 10, "stock_quantity": 3},
        )
        assert product_response.status_code == 201
        product_id = product_response.json()["id"]

        created_before = metric_value(initial, "orders_created_total")
        rejected_before = metric_value(initial, "orders_rejected_total")
        order_response = client.post(
            "/api/orders",
            json={"customer_reference": "METRIC-001", "items": [{"product_id": product_id, "quantity": 1}]},
        )
        assert order_response.status_code == 201
        order_id = order_response.json()["id"]

        after_create = client.get("/metrics").text
        assert metric_value(after_create, "orders_created_total") == created_before + 1
        assert metric_value(after_create, "pending_orders") == 1

        rejected_response = client.post(
            "/api/orders",
            json={"customer_reference": "METRIC-002", "items": [{"product_id": 99999, "quantity": 1}]},
        )
        assert rejected_response.status_code == 404
        after_rejection = client.get("/metrics").text
        assert metric_value(after_rejection, "orders_rejected_total") == rejected_before + 1
        assert metric_value(after_rejection, "pending_orders") == 1

        for status in ("PACKED", "SHIPPED", "COMPLETED"):
            assert client.patch(f"/api/orders/{order_id}/status", json={"status": status}).status_code == 200

        final_metrics = client.get("/metrics").text
        assert metric_value(final_metrics, "orders_completed_total") >= 1
        assert metric_value(final_metrics, "pending_orders") == 0
        assert metric_value(
            final_metrics,
            "order_processing_seconds_count",
            {"terminal_status": "COMPLETED"},
        ) >= 1
        assert metric_value(
            final_metrics,
            "http_requests_total",
            {"method": "POST", "route": "/api/orders", "status_code": "201"},
        ) >= 1
        assert metric_value(
            final_metrics,
            "http_request_duration_seconds_count",
            {"method": "POST", "route": "/api/orders"},
        ) >= 1
