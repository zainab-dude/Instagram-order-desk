import os
import re
import sys
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

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
        ORDERS_CREATED,
        ORDERS_REJECTED,
        ORDER_PROCESSING,
        update_pending_orders,
    )
    from app.models import OrderStatus
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
        ORDERS_CREATED,
        ORDERS_REJECTED,
        ORDER_PROCESSING,
        update_pending_orders,
    )
    from .models import OrderStatus
    from .services import BusinessRuleError, Store


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


def create_app(database_path: Path = DEFAULT_DATABASE_PATH) -> FastAPI:
    @asynccontextmanager
    async def lifespan(_: FastAPI):
        initialize_database(database_path)
        connection = connect(database_path)
        try:
            update_pending_orders(Store(connection))
        finally:
            connection.close()
        yield

    app = FastAPI(title="Observable Instagram Orders", lifespan=lifespan)
    order_latency_fault = OrderLatencyFault()

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

    def business_error(error: BusinessRuleError) -> HTTPException:
        message = str(error)
        status_code = 404 if message in {"product does not exist", "order does not exist"} else 400
        return HTTPException(status_code=status_code, detail=message)

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.get("/api/products")
    def products(store: Store = Depends(get_store)):
        return [product_to_dict(product) for product in store.list_products()]

    @app.post("/api/products", status_code=201)
    def add_product(payload: ProductCreate, store: Store = Depends(get_store)):
        try:
            product = store.add_product(payload.name, payload.variant, payload.price, payload.stock_quantity)
            log_event(20, "stock updated", product_id=product.id)
            return product_to_dict(product)
        except BusinessRuleError as error:
            raise business_error(error) from error

    @app.patch("/api/products/{product_id}/stock")
    def update_stock(product_id: int, payload: StockUpdate, store: Store = Depends(get_store)):
        try:
            product = store.update_stock(product_id, payload.stock_quantity)
            log_event(20, "stock updated", product_id=product_id)
            return product_to_dict(product)
        except BusinessRuleError as error:
            raise business_error(error) from error

    @app.get("/api/orders")
    def orders(store: Store = Depends(get_store)):
        return [order_to_dict(order) for order in store.list_orders()]

    @app.post("/api/orders", status_code=201)
    def add_order(payload: OrderCreate, store: Store = Depends(get_store)):
        try:
            items = [(item.product_id, item.quantity) for item in payload.items]
            order = store.create_order(payload.customer_reference, items)
            ORDERS_CREATED.inc()
            update_pending_orders(store)
            log_event(20, "order created", order_id=order.id)
            return order_to_dict(order)
        except BusinessRuleError as error:
            ORDERS_REJECTED.inc()
            log_event(30, "order rejected")
            raise business_error(error) from error

    @app.patch("/api/orders/{order_id}/status")
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
        except BusinessRuleError as error:
            log_event(30, "order status change rejected", order_id=order_id)
            raise business_error(error) from error

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
        "sold_quantity": product.sold_quantity,  # <-- ADD THIS LINE
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
