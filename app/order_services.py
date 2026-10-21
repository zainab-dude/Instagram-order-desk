"""Shared 'place an order' use case. Called by BOTH the HTTP route and the gRPC handler,
so business rules, metrics and logs behave identically for both."""
import hashlib
import json
from typing import Iterable

from .logging_config import log_event
from .metrics import ORDERS_CREATED, ORDERS_REJECTED, update_pending_orders
from .services import BusinessRuleError, Store


def request_fingerprint(customer_reference: str, items: list[tuple[int, int]]) -> str:
    """Stable hash of the request content, used to detect key reuse with a different body."""
    canonical = json.dumps(
        {"customer_reference": customer_reference.strip(), "items": [list(i) for i in items]},
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


def place_order(
    store: Store,
    customer_reference: str,
    items: Iterable[tuple[int, int]],
    idempotency_key: str | None = None,
):
    """Returns (order, replayed). Raises BusinessRuleError subclasses on failure."""
    items = list(items)
    fingerprint = request_fingerprint(customer_reference, items) if idempotency_key else None
    try:
        order, replayed = store.create_order_idempotent(customer_reference, items, idempotency_key, fingerprint)
    except BusinessRuleError:
        ORDERS_REJECTED.inc()
        log_event(30, "order rejected")
        raise
    if replayed:
        log_event(20, "order replayed", order_id=order.id)
        return order, True
    ORDERS_CREATED.inc()
    update_pending_orders(store)
    log_event(20, "order created", order_id=order.id)
    return order, False