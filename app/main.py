import math
import os
import re
import sys
import threading
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import Depends, FastAPI, Header, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from starlette.exceptions import HTTPException as StarletteHTTPException

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from app.database import DEFAULT_DATABASE_PATH, connect, initialize_database
    from app.logging_config import REQUEST_ID, log_event
    from app.experiment_fault import OrderLatencyFault
    from app.metrics import (
        HTTP_REQUEST_DURATION,
        HTTP_REQUESTS,
        ORDERS_CANCELLED,
        ORDERS_COMPLETED,
        ORDER_PROCESSING,
        update_pending_orders,
    )
    from app.models import OrderStatus
    from app.order_services import place_order
    from app.services import BusinessRuleError, Store
else:
    from .database import DEFAULT_DATABASE_PATH, connect, initialize_database
    from .logging_config import REQUEST_ID, log_event
    from .experiment_fault import OrderLatencyFault
    from .metrics import (
        HTTP_REQUEST_DURATION,
        HTTP_REQUESTS,
        ORDERS_CANCELLED,
        ORDERS_COMPLETED,
        ORDER_PROCESSING,
        update_pending_orders,
    )
    from .models import OrderStatus
    from .order_services import place_order
    from .services import BusinessRuleError, Store


# ---------- Request models ----------
class ProductCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    variant: str = Field(default="", max_length=120)
    price: float = Field(ge=0)
    stock_quantity: int = Field(ge=0)


class StockUpdate(BaseModel):
    stock_quantity: int = Field(ge=0)


class OrderItemCreate(BaseModel):
    product_id: int = Field(gt=0)
    quantity: int = Field(gt=0)


class OrderCreate(BaseModel):
    customer_reference: str = Field(min_length=1, max_length=120)
    items: list[OrderItemCreate] = Field(min_length=1)


class StatusUpdate(BaseModel):
    status: OrderStatus


# ---------- Response models (drive the OpenAPI document) ----------
class ProductOut(BaseModel):
    id: int
    name: str
    variant: str
    price: float
    stock_quantity: int
    reserved_quantity: int
    available_quantity: int
    sold_quantity: int


class OrderItemOut(BaseModel):
    product_id: int
    product_name: str
    variant: str
    quantity: int
    unit_price: float


class OrderOut(BaseModel):
    id: int
    customer_reference: str
    status: str
    total: float
    created_at: str
    items: list[OrderItemOut]


class ErrorBody(BaseModel):
    code: str
    message: str
    details: list[dict] | None = None


class ErrorResponse(BaseModel):
    error: ErrorBody


_ERROR_TEXT = {
    404: "Resource not found",
    409: "Conflict with current state (e.g. insufficient stock, invalid status transition)",
    422: "Validation error (bad input or misused Idempotency-Key)",
    429: "Rate limit exceeded; see Retry-After header",
}


def error_docs(*codes: int) -> dict:
    return {code: {"model": ErrorResponse, "description": _ERROR_TEXT[code]} for code in codes}


# ---------- Consistent errors ----------
class ApiError(Exception):
    def __init__(self, status_code: int, code: str, message: str, headers: dict | None = None):
        self.status_code = status_code
        self.code = code
        self.message = message
        self.headers = headers


def error_response(status_code: int, code: str, message: str, headers: dict | None = None, details=None):
    body = {"code": code, "message": message}
    if details:
        body["details"] = details
    return JSONResponse(status_code=status_code, content={"error": body}, headers=headers)


# ---------- Rate limiting (single instance, in memory) ----------
class FixedWindowLimiter:
    def __init__(self, limit: int, window_seconds: float, clock=time.monotonic):
        self.limit = limit
        self.window = window_seconds
        self._clock = clock
        self._hits: dict[str, tuple[float, int]] = {}
        self._lock = threading.Lock()

    def check(self, key: str) -> int:
        """0 = allowed. Otherwise seconds until the window resets (for Retry-After)."""
        with self._lock:
            now = self._clock()
            start, count = self._hits.get(key, (now, 0))
            if now - start >= self.window:
                start, count = now, 0
            if count >= self.limit:
                return max(1, math.ceil(start + self.window - now))
            self._hits[key] = (start, count + 1)
            return 0


def create_app(
    database_path: Path = DEFAULT_DATABASE_PATH,
    rate_limit: int | None = None,
    rate_window: float | None = None,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(_: FastAPI):
        initialize_database(database_path)
        connection = connect(database_path)
        try:
            update_pending_orders(Store(connection))
        finally:
            connection.close()
        yield

    app = FastAPI(
        title="Observable Instagram Orders",
        version="2.0.0",
        description="Order and inventory API. POST /api/orders supports Idempotency-Key and is rate limited.",
        lifespan=lifespan,
    )
    order_latency_fault = OrderLatencyFault()

    # Limit applies to POST /api/orders only. Shared per client IP.
    limiter = FixedWindowLimiter(
        rate_limit if rate_limit is not None else int(os.getenv("RATE_LIMIT_MAX", "5")),
        rate_window if rate_window is not None else float(os.getenv("RATE_LIMIT_WINDOW", "10")),
    )

    def limit_order_creation(request: Request):
        client = request.client.host if request.client else "unknown"
        retry_after = limiter.check(client)
        if retry_after:
            raise ApiError(
                429,
                "rate_limited",
                f"Too many order requests. Retry in {retry_after} seconds.",
                headers={"Retry-After": str(retry_after)},
            )

    # ----- exception handlers: every error becomes {"error": {"code", "message"}} -----
    @app.exception_handler(ApiError)
    async def api_error_handler(_: Request, error: ApiError):
        return error_response(error.status_code, error.code, error.message, error.headers)

    @app.exception_handler(BusinessRuleError)
    async def business_error_handler(_: Request, error: BusinessRuleError):
        return error_response(error.http_status, error.code, str(error))

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(_: Request, error: RequestValidationError):
        details = [
            {"field": ".".join(str(part) for part in item["loc"]), "message": item["msg"]}
            for item in error.errors()
        ]
        return error_response(422, "validation_error", "request validation failed", details=details)

    @app.exception_handler(StarletteHTTPException)
    async def http_error_handler(_: Request, error: StarletteHTTPException):
        code = {404: "not_found", 405: "method_not_allowed"}.get(error.status_code, "http_error")
        return error_response(error.status_code, code, str(error.detail), error.headers)

    @app.middleware("http")
    async def record_http_metrics(request, call_next):
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        request_id_token = REQUEST_ID.set(request_id)
        started_at = time.perf_counter()
        try:
            await order_latency_fault.before_request(request.method, request.url.path)
            response = await call_next(request)
        except Exception as error:
            duration = time.perf_counter() - started_at
            route = metric_route(request.url.path)
            HTTP_REQUESTS.labels(request.method, route, "500").inc()
            HTTP_REQUEST_DURATION.labels(request.method, route).observe(duration)
            log_event(40, "unexpected application error", method=request.method, path=request.url.path,
                      status_code=500, duration_ms=round(duration * 1000, 2), error_type=type(error).__name__)
            raise
        finally:
            REQUEST_ID.reset(request_id_token)
        route = metric_route(request.url.path)
        duration = time.perf_counter() - started_at
        labels = (request.method, route)
        HTTP_REQUESTS.labels(request.method, route, str(response.status_code)).inc()
        HTTP_REQUEST_DURATION.labels(*labels).observe(duration)
        response.headers["X-Request-ID"] = request_id
        if response.status_code >= 500:
            severity = 40
            message = "request failed"
        elif response.status_code >= 400:
            severity = 30
            message = "invalid request"
        else:
            severity = 20
            message = "request completed"
        request_id_token = REQUEST_ID.set(request_id)
        try:
            log_event(severity, message, method=request.method, path=request.url.path, status_code=response.status_code, duration_ms=round(duration * 1000, 2))
        finally:
            REQUEST_ID.reset(request_id_token)
        return response

    def get_store():
        connection = connect(database_path)
        try:
            yield Store(connection)
        finally:
            connection.close()

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.get("/api/products", response_model=list[ProductOut], summary="List products")
    def products(store: Store = Depends(get_store)):
        return [product_to_dict(product) for product in store.list_products()]

    @app.post("/api/products", status_code=201, response_model=ProductOut, summary="Create a product",
              responses=error_docs(409, 422))
    def add_product(payload: ProductCreate, store: Store = Depends(get_store)):
        product = store.add_product(payload.name, payload.variant, payload.price, payload.stock_quantity)
        log_event(20, "stock updated", product_id=product.id)
        return product_to_dict(product)

    @app.patch("/api/products/{product_id}/stock", response_model=ProductOut, summary="Set physical stock",
               responses=error_docs(404, 409, 422))
    def update_stock(product_id: int, payload: StockUpdate, store: Store = Depends(get_store)):
        product = store.update_stock(product_id, payload.stock_quantity)
        log_event(20, "stock updated", product_id=product_id)
        return product_to_dict(product)

    @app.get("/api/orders", response_model=list[OrderOut], summary="List orders")
    def orders(store: Store = Depends(get_store)):
        return [order_to_dict(order) for order in store.list_orders()]

    @app.post(
        "/api/orders",
        status_code=201,
        response_model=OrderOut,
        summary="Place an order",
        description=(
            "Reserves stock and creates a PENDING order. Send an `Idempotency-Key` header (1-128 chars) "
            "to make retries safe: repeating the same key and body returns the original order "
            "(header `Idempotent-Replay: true`) without a second order or reservation. "
            "The same key with a different body returns 422. Limited per client IP; "
            "exceeding the limit returns 429 with `Retry-After`."
        ),
        responses=error_docs(404, 409, 422, 429),
        dependencies=[Depends(limit_order_creation)],
    )
    def add_order(
        payload: OrderCreate,
        response: Response,
        store: Store = Depends(get_store),
        idempotency_key: str | None = Header(default=None, description="Unique key per logical order attempt"),
    ):
        if idempotency_key is not None and not (1 <= len(idempotency_key) <= 128):
            raise ApiError(422, "invalid_idempotency_key", "Idempotency-Key must be 1-128 characters")
        items = [(item.product_id, item.quantity) for item in payload.items]
        order, replayed = place_order(store, payload.customer_reference, items, idempotency_key)
        if replayed:
            response.headers["Idempotent-Replay"] = "true"
        return order_to_dict(order)

    @app.patch("/api/orders/{order_id}/status", response_model=OrderOut, summary="Change order status",
               description="Repeat-safe: repeating a transition is rejected with 409 and changes no stock.",
               responses=error_docs(404, 409, 422))
    def update_order_status(order_id: int, payload: StatusUpdate, store: Store = Depends(get_store)):
        try:
            previous_status = store.get_order(order_id).status.value
            order = store.change_order_status(order_id, payload.status)
            if payload.status is OrderStatus.COMPLETED:
                ORDERS_COMPLETED.inc()
            elif payload.status is OrderStatus.CANCELLED:
                ORDERS_CANCELLED.inc()
            if payload.status in {OrderStatus.COMPLETED, OrderStatus.CANCELLED}:
                ORDER_PROCESSING.labels(terminal_status=payload.status.value).observe(processing_seconds(order))
            update_pending_orders(store)
            log_event(20, "order cancelled" if payload.status is OrderStatus.CANCELLED else "order status changed", order_id=order.id, old_status=previous_status, new_status=payload.status.value)
            return order_to_dict(order)
        except BusinessRuleError:
            log_event(30, "order status change rejected", order_id=order_id)
            raise

    @app.get("/metrics", include_in_schema=False)
    def metrics():
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    app.mount("/", StaticFiles(directory=Path(__file__).parent / "static", html=True), name="static")
    return app


def product_to_dict(product):
    return {
        "id": product.id,
        "name": product.name,
        "variant": product.variant,
        "price": product.price_cents / 100,
        "stock_quantity": product.stock_quantity,
        "reserved_quantity": product.reserved_quantity,
        "available_quantity": product.available_quantity,
        "sold_quantity": product.sold_quantity,
    }


def order_to_dict(order):
    return {
        "id": order.id,
        "customer_reference": order.customer_reference,
        "status": order.status.value,
        "total": order.total_cents / 100,
        "created_at": order.created_at,
        "items": [
            {
                "product_id": item.product_id,
                "product_name": item.product_name,
                "variant": item.variant,
                "quantity": item.quantity,
                "unit_price": item.unit_price_cents / 100,
            }
            for item in order.items
        ],
    }


def processing_seconds(order) -> float:
    created_at = datetime.fromisoformat(order.created_at).replace(tzinfo=timezone.utc)
    return max(0.0, (datetime.now(timezone.utc) - created_at).total_seconds())


def metric_route(path: str) -> str:
    if path in {"/", "/health", "/metrics", "/api/products", "/api/orders", "/styles.css", "/app.js"}:
        return path
    if re.fullmatch(r"/api/products/\d+/stock", path):
        return "/api/products/{product_id}/stock"
    if re.fullmatch(r"/api/orders/\d+/status", path):
        return "/api/orders/{order_id}/status"
    return "unmatched"


app = create_app(Path(os.getenv("DATABASE_PATH", str(DEFAULT_DATABASE_PATH))))


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)