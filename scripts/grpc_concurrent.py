import concurrent.futures
import time
import uuid

import grpc

import app.grpc_gen.orders_pb2 as pb
import app.grpc_gen.orders_pb2_grpc as pb_grpc


SERVER_ADDR = "localhost:50051"
WORKERS = 8
DURATION_SECONDS = 90


def send_call(worker_id: int, stub) -> str:
    request = pb.CreateOrderRequest(
        customer_reference=f"CONCURRENT-{worker_id}-{uuid.uuid4()}",
        items=[pb.OrderItem(product_id=999999, quantity=1)],
        idempotency_key=str(uuid.uuid4()),
    )
    try:
        stub.CreateOrder(request, timeout=5)
        return "OK"
    except grpc.RpcError as error:
        return error.code().name


def worker(worker_id: int, deadline: float) -> int:
    channel = grpc.insecure_channel(SERVER_ADDR)
    stub = pb_grpc.OrderServiceStub(channel)
    calls = 0
    try:
        while time.monotonic() < deadline:
            send_call(worker_id, stub)
            calls += 1
    finally:
        channel.close()
    return calls


def main() -> None:
    deadline = time.monotonic() + DURATION_SECONDS
    print(f"Starting {WORKERS} concurrent gRPC workers for about {DURATION_SECONDS}s")
    with concurrent.futures.ThreadPoolExecutor(max_workers=WORKERS) as executor:
        futures = [executor.submit(worker, worker_id, deadline) for worker_id in range(WORKERS)]
        counts = [future.result() for future in futures]
    print(f"Concurrent load complete: {sum(counts)} calls across {WORKERS} workers")


if __name__ == "__main__":
    main()
