import argparse
import sys
import uuid

import grpc

import app.grpc_gen.orders_pb2 as pb
import app.grpc_gen.orders_pb2_grpc as pb_grpc


def main():
    parser = argparse.ArgumentParser(description="gRPC client to place an order.")
    parser.add_argument("--product-id", type=int, required=True, help="Product ID to purchase")
    parser.add_argument("--quantity", type=int, required=True, help="Quantity to purchase")
    parser.add_argument("--reference", type=str, default="CLI-ORDER", help="Customer reference")
    parser.add_argument("--idempotency-key", type=str, default=None, help="Optional idempotency key")
    parser.add_argument("--timeout", type=float, default=2.0, help="RPC timeout in seconds (default: 2)")
    parser.add_argument("--server", type=str, default="localhost:50051", help="gRPC server address")
    parser.add_argument("--request-id", type=str, default=None, help="Optional request ID for log correlation")
    args = parser.parse_args()

    rid = args.request_id or f"grpc-cli-{uuid.uuid4()}"
    metadata = (("x-request-id", rid),)
    request = pb.CreateOrderRequest(
        customer_reference=args.reference,
        items=[pb.OrderItem(product_id=args.product_id, quantity=args.quantity)],
        idempotency_key=args.idempotency_key or str(uuid.uuid4()),
    )

    channel = grpc.insecure_channel(args.server)
    stub = pb_grpc.OrderServiceStub(channel)

    try:
        print(f"REQUEST_ID: {rid}")
        response = stub.CreateOrder(request, timeout=args.timeout, metadata=metadata)
        print(
            f"SUCCESS: Order ID={response.order_id}, Status={response.status}, "
            f"Total={response.total:.2f}, Replayed={response.replayed}"
        )
    except grpc.RpcError as error:
        print(f"RPC ERROR: Code={error.code().name}, Details={error.details()}")
        sys.exit(1)
    finally:
        channel.close()


if __name__ == "__main__":
    main()
