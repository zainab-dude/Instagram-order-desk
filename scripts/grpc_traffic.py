import time
import uuid
import os

import grpc

import app.grpc_gen.orders_pb2 as pb
import app.grpc_gen.orders_pb2_grpc as pb_grpc


SERVER_ADDR = "localhost:50051"
PRODUCT_ID = int(os.getenv("GRPC_PRODUCT_ID", "14"))


def send_rpc(stub, reference, items, idempotency_key=None, timeout=2.0):
    request_id = f"traffic-{uuid.uuid4()}"
    metadata = (("x-request-id", request_id),)
    request = pb.CreateOrderRequest(
        customer_reference=reference,
        items=[pb.OrderItem(product_id=item[0], quantity=item[1]) for item in items],
        idempotency_key=idempotency_key or str(uuid.uuid4()),
    )

    try:
        response = stub.CreateOrder(request, timeout=timeout, metadata=metadata)
        print(
            f"  [OK] Order #{response.order_id} | Status: {response.status} "
            f"| Total: ${response.total:.2f}"
        )
        return "OK"
    except grpc.RpcError as error:
        print(f"  [ERROR] Code: {error.code().name} | Details: {error.details()}")
        return error.code().name


def main():
    channel = grpc.insecure_channel(SERVER_ADDR)
    stub = pb_grpc.OrderServiceStub(channel)

    print("========================================")
    print(" 1. Sending 5 Valid Requests (Expected: OK)")
    print("========================================")
    for index in range(1, 6):
        print(f"Call {index}/5:")
        send_rpc(stub, f"VALID-{index}", [(PRODUCT_ID, 1)])
        time.sleep(0.2)

    print("\n========================================")
    print(" 2. Sending 2 Requests with Quantity=0 (Expected: INVALID_ARGUMENT)")
    print("========================================")
    for index in range(1, 3):
        print(f"Call {index}/2:")
        send_rpc(stub, f"ZERO-QTY-{index}", [(PRODUCT_ID, 0)])
        time.sleep(0.2)

    print("\n========================================")
    print(" 3. Sending 2 Requests Over Available Stock (Expected: FAILED_PRECONDITION)")
    print("========================================")
    for index in range(1, 3):
        print(f"Call {index}/2:")
        send_rpc(stub, f"OVERSTOCK-{index}", [(PRODUCT_ID, 99999)])
        time.sleep(0.2)

    print("\n========================================")
    print(" 4. Sending 1 Request with Unknown Product (Expected: NOT_FOUND)")
    print("========================================")
    print("Call 1/1:")
    send_rpc(stub, "UNKNOWN-PROD", [(999999, 1)])

    print(
        "\nTraffic generation complete. Total calls: 10 "
        "(5 OK, 2 INVALID_ARGUMENT, 2 FAILED_PRECONDITION, 1 NOT_FOUND)"
    )
    channel.close()


if __name__ == "__main__":
    main()
