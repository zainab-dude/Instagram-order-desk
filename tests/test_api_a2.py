from fastapi.testclient import TestClient
from app.main import create_app

def make_client(tmp_path, limit=1000, window=10):
    return TestClient(create_app(tmp_path / "t.db", rate_limit=limit, rate_window=window))

def add_product(client, stock=5):
    r = client.post("/api/products", json={"name": "Mug", "variant": "", "price": 5, "stock_quantity": stock})
    return r.json()["id"]

def order_body(pid, qty=1):
    return {"customer_reference": "TEST-1", "items": [{"product_id": pid, "quantity": qty}]}

def test_valid_order(tmp_path):
    with make_client(tmp_path) as c:
        pid = add_product(c)
        r = c.post("/api/orders", json=order_body(pid))
        assert r.status_code == 201 and r.json()["status"] == "PENDING"

def test_invalid_input(tmp_path):
    with make_client(tmp_path) as c:
        pid = add_product(c)
        r = c.post("/api/orders", json=order_body(pid, -5))
        assert r.status_code == 422
        assert r.json()["error"]["code"] == "validation_error"

def test_repeated_key_creates_one_order(tmp_path):
    with make_client(tmp_path) as c:
        pid = add_product(c)
        h = {"Idempotency-Key": "k1"}
        a = c.post("/api/orders", json=order_body(pid), headers=h)
        b = c.post("/api/orders", json=order_body(pid), headers=h)
        assert a.json()["id"] == b.json()["id"]
        assert b.headers["Idempotent-Replay"] == "true"
        assert len(c.get("/api/orders").json()) == 1
        assert c.get("/api/products").json()[0]["reserved_quantity"] == 1

def test_same_key_different_body_rejected(tmp_path):
    with make_client(tmp_path) as c:
        pid = add_product(c)
        h = {"Idempotency-Key": "k2"}
        c.post("/api/orders", json=order_body(pid, 1), headers=h)
        r = c.post("/api/orders", json=order_body(pid, 2), headers=h)
        assert r.status_code == 422
        assert r.json()["error"]["code"] == "idempotency_key_reuse"

def test_rate_limit_429(tmp_path):
    with make_client(tmp_path, limit=2) as c:
        pid = add_product(c)
        codes = [c.post("/api/orders", json=order_body(pid)).status_code for _ in range(3)]
        assert codes == [201, 201, 429]
        r = c.post("/api/orders", json=order_body(pid))
        assert int(r.headers["Retry-After"]) >= 1
        assert r.json()["error"]["code"] == "rate_limited"