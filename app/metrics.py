from prometheus_client import Counter, Gauge, Histogram, Summary


HTTP_REQUESTS = Counter(
    "http_requests_total",
    "Total HTTP requests handled by the application.",
    ("method", "route", "status_code"),
)
HTTP_REQUEST_DURATION = Histogram(
    "http_request_duration_seconds",
    "HTTP request duration in seconds.",
    ("method", "route"),
)
ORDERS_CREATED = Counter("orders_created_total", "Total orders created.")
ORDERS_COMPLETED = Counter("orders_completed_total", "Total orders completed.")
ORDERS_CANCELLED = Counter("orders_cancelled_total", "Total orders cancelled.")
ORDERS_REJECTED = Counter("orders_rejected_total", "Total order creation attempts rejected by business rules.")
PENDING_ORDERS = Gauge("pending_orders", "Current number of orders with PENDING status.")
ORDER_PROCESSING = Summary(
    "order_processing_seconds",
    "Time from order creation until it reaches a terminal status.",
    ("terminal_status",),
)


def update_pending_orders(store) -> None:
    PENDING_ORDERS.set(store.count_orders("PENDING"))
