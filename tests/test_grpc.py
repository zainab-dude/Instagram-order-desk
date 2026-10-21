from concurrent import futures
from pathlib import Path

import grpc
import pytest

import app.grpc_gen.orders_pb2 as pb
import app.grpc_gen.orders_pb2_grpc as pb_grpc
from app.database import connect, initialize_database
from app.services import Store
from grpc_server import server as grpc_server


@pytest.fixture
def grpc_stub(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    database_path = tmp_path / "orders.db"
    initialize_database(database_path)
    with connect(database_path) as connection:
        product = Store(connection).add_product("Test Mug", "", 5, 2)

    monkeypatch.setattr(grpc_server, "DATABASE_PATH", database_path)
    service = grpc.server(futures.ThreadPoolExecutor(max_workers=2))
    pb_grpc.add_OrderServiceServicer_to_server(grpc_server.OrderServicer(), service)
    port = service.add_insecure_port("localhost:0")
    service.start()
    channel = grpc.insecure_channel(f"localhost:{port}")
    try:
        yield pb_grpc.OrderServiceStub(channel), product.id
    finally:
        channel.close()
        service.stop(0).wait()


def request(product_id: int, quantity: int = 1) -> pb.CreateOrderRequest:
    return pb.CreateOrderRequest(
        customer_reference="GRPC-TEST",
        items=[pb.OrderItem(product_id=product_id, quantity=quantity)],
    )


def test_create_order_success(grpc_stub):
    stub, product_id = grpc_stub
    response = stub.CreateOrder(request(product_id))
    assert response.status == "PENDING"
    assert response.order_id > 0


@pytest.mark.parametrize(
    ("product_id", "quantity", "status"),
    [
        (1, 0, grpc.StatusCode.INVALID_ARGUMENT),
        (99999, 1, grpc.StatusCode.NOT_FOUND),
        (1, 99999, grpc.StatusCode.FAILED_PRECONDITION),
    ],
)
def test_create_order_error_codes(grpc_stub, product_id, quantity, status):
    stub, actual_product_id = grpc_stub
    if product_id == 1:
        product_id = actual_product_id
    with pytest.raises(grpc.RpcError) as raised:
        stub.CreateOrder(request(product_id, quantity))
    assert raised.value.code() == status
