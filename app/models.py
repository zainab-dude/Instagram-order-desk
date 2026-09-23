from dataclasses import dataclass
from enum import Enum
from typing import Optional


class OrderStatus(str, Enum):
    PENDING = "PENDING"
    PACKED = "PACKED"
    SHIPPED = "SHIPPED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


ALLOWED_STATUS_TRANSITIONS = {
    OrderStatus.PENDING: {OrderStatus.PACKED, OrderStatus.CANCELLED},
    OrderStatus.PACKED: {OrderStatus.SHIPPED, OrderStatus.CANCELLED},
    OrderStatus.SHIPPED: {OrderStatus.COMPLETED, OrderStatus.CANCELLED},
    OrderStatus.COMPLETED: set(),
    OrderStatus.CANCELLED: set(),
}


@dataclass(frozen=True)
class Product:
    id: int
    name: str
    variant: str
    price_cents: int
    stock_quantity: int
    reserved_quantity: int
    sold_quantity: int = 0  # Populated via query or aggregation

    @property
    def available_quantity(self) -> int:
        return self.stock_quantity - self.reserved_quantity


@dataclass(frozen=True)
class OrderItem:
    product_id: int
    product_name: str
    variant: str
    quantity: int
    unit_price_cents: int


@dataclass(frozen=True)
class Order:
    id: int
    customer_reference: str
    status: OrderStatus
    total_cents: int
    created_at: str
    items: tuple[OrderItem, ...]
