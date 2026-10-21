import os
import sys
import uuid
import time
import grpc
from concurrent import futures
from prometheus_client import Counter, Gauge, Histogram, start_http_server
from pathlib import Path

import app.grpc_gen.orders_pb2 as pb
import app.grpc_gen.orders_pb2_grpc as pb_grpc

from app.order_services import place_order
from app.database import connect
from app.services import IdempotencyKeyReuseError, NotFoundError, ConflictError, BusinessRuleError, Store
from app.logging_config import REQUEST_ID, log_event

DATABASE_PATH = Path(os.getenv("DATABASE_PATH", "data/orders.db"))
GRPC_PORT = os.getenv("GRPC_PORT", "50051")
METRICS_PORT = int(os.getenv("METRICS_PORT", "8002"))
GRPC_SERVICE = "orders.v1.OrderService"
GRPC_METHOD = "CreateOrder"

GRPC_HANDLED_TOTAL = Counter(
    "grpc_server_handled_total",
    "Completed gRPC calls by method and status code.",
    ("grpc_service", "grpc_method", "grpc_code"),
)
GRPC_HANDLING_SECONDS = Histogram(
    "grpc_server_handling_seconds",
    "Time spent handling gRPC calls in seconds.",
    ("grpc_service", "grpc_method"),
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0),
)
GRPC_IN_FLIGHT_REQUESTS = Gauge(
    "grpc_server_in_flight_requests",
    "Current number of in-flight gRPC calls.",
    ("grpc_service", "grpc_method"),
)


class OrderServicer(pb_grpc.OrderServiceServicer):
    def CreateOrder(self, request, context):
        started_at = time.perf_counter()
        GRPC_IN_FLIGHT_REQUESTS.labels(GRPC_SERVICE, GRPC_METHOD).inc()
        grpc_code = "UNKNOWN"
        metadata = dict(context.invocation_metadata())
        rid = metadata.get("x-request-id") or str(uuid.uuid4())
        token = REQUEST_ID.set(rid)

        try:
            delay_ms = int(os.getenv("GRPC_DEMO_DELAY_MS", "0"))
            if delay_ms > 0:
                time.sleep(delay_ms / 1000)
            with connect(DATABASE_PATH) as connection:
                store = Store(connection)
                items = [(it.product_id, it.quantity) for it in request.items]

                log_event(
                    20,
                    "gRPC CreateOrder request received",
                    method="CreateOrder",
                    path="/orders.v1.OrderService/CreateOrder",
                )
                order, replayed = place_order(
                    store,
                    request.customer_reference,
                    items,
                    request.idempotency_key or None,
                )
                log_event(20, "gRPC CreateOrder completed successfully", order_id=order.id)
                grpc_code = "OK"

                return pb.CreateOrderResponse(
                    order_id=order.id,
                    status=order.status.value,
                    total=order.total_cents / 100,
                    replayed=replayed,
                )

        except IdempotencyKeyReuseError as e:
            grpc_code = grpc.StatusCode.INVALID_ARGUMENT.name
            log_event(30, f"Idempotency violation: {e}")
            context.abort(grpc.StatusCode.INVALID_ARGUMENT, str(e))
        except NotFoundError as e:
            grpc_code = grpc.StatusCode.NOT_FOUND.name
            log_event(30, f"Resource not found: {e}")
            context.abort(grpc.StatusCode.NOT_FOUND, str(e))
        except ConflictError as e:
            grpc_code = grpc.StatusCode.FAILED_PRECONDITION.name
            log_event(30, f"State conflict: {e}")
            context.abort(grpc.StatusCode.FAILED_PRECONDITION, str(e))
        except BusinessRuleError as e:
            grpc_code = grpc.StatusCode.INVALID_ARGUMENT.name
            log_event(30, f"Business rule error: {e}")
            context.abort(grpc.StatusCode.INVALID_ARGUMENT, str(e))
        except Exception as e:
            grpc_code = grpc.StatusCode.INTERNAL.name
            log_event(40, "Unhandled error in CreateOrder", error_type=type(e).__name__)
            context.abort(grpc.StatusCode.INTERNAL, "Internal server error")
        finally:
            labels = (GRPC_SERVICE, GRPC_METHOD)
            GRPC_HANDLED_TOTAL.labels(*labels, grpc_code).inc()
            GRPC_HANDLING_SECONDS.labels(*labels).observe(time.perf_counter() - started_at)
            GRPC_IN_FLIGHT_REQUESTS.labels(*labels).dec()
            REQUEST_ID.reset(token)


def serve():
    # Start Prometheus HTTP scrape endpoint on port 8002
    start_http_server(METRICS_PORT)
    log_event(20, f"gRPC Prometheus metrics exporter listening on port {METRICS_PORT}")

    # Initialize gRPC server on 50051
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    pb_grpc.add_OrderServiceServicer_to_server(OrderServicer(), server)
    server.add_insecure_port(f"[::]:{GRPC_PORT}")
    server.start()
    log_event(20, f"OrderService gRPC server started on [::]:{GRPC_PORT}")
    server.wait_for_termination()


if __name__ == "__main__":
    serve()