import sqlite3

import pytest

from app.database import SCHEMA
from app.models import OrderStatus
from app.services import BusinessRuleError, Store


@pytest.fixture
def store():
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.executescript(SCHEMA)
    yield Store(connection)
    connection.close()


def test_create_order_reserves_stock_and_calculates_total(store):
    product = store.add_product("Canvas Tote", "Natural", "12.50", 5)
    order = store.create_order("DM-001", [(product.id, 2)])

    assert order.status is OrderStatus.PENDING
    assert order.total_cents == 2500
    assert store.get_product(product.id).available_quantity == 3
    assert store.get_product(product.id).reserved_quantity == 2


def test_insufficient_stock_does_not_create_order_or_change_stock(store):
    product = store.add_product("Sticker Pack", "", 5, 2)

    with pytest.raises(BusinessRuleError, match="insufficient stock"):
        store.create_order("DM-002", [(product.id, 3)])

    assert store.list_orders() == []
    assert store.get_product(product.id).available_quantity == 2


def test_unknown_product_is_rejected(store):
    with pytest.raises(BusinessRuleError, match="product does not exist"):
        store.create_order("DM-003", [(999, 1)])


def test_cancellation_restores_reserved_stock_once(store):
    product = store.add_product("Mug", "Blue", 10, 4)
    order = store.create_order("DM-004", [(product.id, 3)])

    cancelled = store.change_order_status(order.id, OrderStatus.CANCELLED)
    assert cancelled.status is OrderStatus.CANCELLED
    assert store.get_product(product.id).available_quantity == 4
    assert store.get_product(product.id).reserved_quantity == 0

    with pytest.raises(BusinessRuleError, match="cannot change order"):
        store.change_order_status(order.id, OrderStatus.CANCELLED)


def test_valid_lifecycle_and_invalid_skip(store):
    product = store.add_product("Cap", "Black", 20, 2)
    order = store.create_order("DM-005", [(product.id, 1)])

    for status in (OrderStatus.PACKED, OrderStatus.SHIPPED, OrderStatus.COMPLETED):
        order = store.change_order_status(order.id, status)
    assert order.status is OrderStatus.COMPLETED

    with pytest.raises(BusinessRuleError, match="cannot change order"):
        store.change_order_status(order.id, OrderStatus.PENDING)


def test_invalid_quantities_and_stock_update_are_rejected(store):
    product = store.add_product("Notebook", "A5", 3, 4)
    with pytest.raises(BusinessRuleError, match="quantities must be positive"):
        store.create_order("DM-006", [(product.id, 0)])

    order = store.create_order("DM-007", [(product.id, 2)])
    with pytest.raises(BusinessRuleError, match="lower than already reserved"):
        store.update_stock(product.id, 1)
    assert order.items[0].quantity == 2


def test_stale_cancellation_cannot_restore_packed_stock_twice(store, monkeypatch):
    product = store.add_product("Race Test", "", 1, 5)
    order = store.create_order("TEST", [(product.id, 2)])
    store.change_order_status(order.id, OrderStatus.PACKED)
    original_read = store.get_order
    competing_store = Store(store.connection)
    first_read = True

    def read_with_competing_cancellation(order_id):
        nonlocal first_read
        snapshot = original_read(order_id)
        if first_read:
            first_read = False
            competing_store.change_order_status(order_id, OrderStatus.CANCELLED)
        return snapshot

    monkeypatch.setattr(store, "get_order", read_with_competing_cancellation)
    with pytest.raises(BusinessRuleError, match="changed concurrently"):
        store.change_order_status(order.id, OrderStatus.CANCELLED)
    assert store.get_product(product.id).stock_quantity == 5
    assert store.get_product(product.id).reserved_quantity == 0
    assert original_read(order.id).status == OrderStatus.CANCELLED
