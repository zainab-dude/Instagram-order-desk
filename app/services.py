import sqlite3
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Iterable

from .models import (
    ALLOWED_STATUS_TRANSITIONS,
    Order,
    OrderItem,
    OrderStatus,
    Product,
)


class BusinessRuleError(ValueError):
    pass


def money_to_cents(price: Decimal | float | int | str) -> int:
    try:
        amount = Decimal(str(price)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError):
        raise BusinessRuleError("price must be a valid number") from None
    if amount < 0:
        raise BusinessRuleError("price cannot be negative")
    return int(amount * 100)


class Store:
    def __init__(self, connection: sqlite3.Connection):
        self.connection = connection

    _PRODUCT_BASE_QUERY = """
        SELECT 
            p.id,
            p.name,
            p.variant,
            p.price_cents,
            p.stock_quantity,
            p.reserved_quantity,
            COALESCE(
                SUM(
                    CASE 
                        WHEN o.id IS NOT NULL THEN oi.quantity 
                        ELSE 0 
                    END
                ), 
                0
            ) AS sold_quantity
        FROM products p
        LEFT JOIN order_items oi ON p.id = oi.product_id
        LEFT JOIN orders o ON oi.order_id = o.id AND o.status IN ('PACKED', 'SHIPPED', 'COMPLETED')
    """

    def list_products(self) -> list[Product]:
        query = f"{self._PRODUCT_BASE_QUERY} GROUP BY p.id ORDER BY p.name, p.variant"
        rows = self.connection.execute(query).fetchall()
        return [self._product(row) for row in rows]

    def add_product(self, name: str, variant: str, price: Decimal | float | int | str, stock_quantity: int) -> Product:
        name = name.strip()
        variant = variant.strip()
        if not name:
            raise BusinessRuleError("product name is required")
        if stock_quantity < 0:
            raise BusinessRuleError("stock quantity cannot be negative")
        try:
            cursor = self.connection.execute(
                "INSERT INTO products (name, variant, price_cents, stock_quantity) VALUES (?, ?, ?, ?)",
                (name, variant, money_to_cents(price), stock_quantity),
            )
            self.connection.commit()
        except sqlite3.IntegrityError as error:
            raise BusinessRuleError("a product with this name and variant already exists") from error
        return self.get_product(cursor.lastrowid)

    def get_product(self, product_id: int) -> Product:
        query = f"{self._PRODUCT_BASE_QUERY} WHERE p.id = ? GROUP BY p.id"
        row = self.connection.execute(query, (product_id,)).fetchone()
        if row is None:
            raise BusinessRuleError("product does not exist")
        return self._product(row)

    def update_stock(self, product_id: int, stock_quantity: int) -> Product:
        if stock_quantity < 0:
            raise BusinessRuleError("stock quantity cannot be negative")
        product = self.get_product(product_id)
        if stock_quantity < product.reserved_quantity:
            raise BusinessRuleError("stock cannot be lower than already reserved quantity")
        self.connection.execute("UPDATE products SET stock_quantity = ? WHERE id = ?", (stock_quantity, product_id))
        self.connection.commit()
        return self.get_product(product_id)

    def list_orders(self) -> list[Order]:
        rows = self.connection.execute("SELECT * FROM orders ORDER BY id DESC").fetchall()
        return [self._order(row) for row in rows]

    def count_orders(self, status: str) -> int:
        row = self.connection.execute("SELECT COUNT(*) AS count FROM orders WHERE status = ?", (status,)).fetchone()
        return row["count"]

    def get_order(self, order_id: int) -> Order:
        row = self.connection.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
        if row is None:
            raise BusinessRuleError("order does not exist")
        return self._order(row)

    def create_order(self, customer_reference: str, items: Iterable[tuple[int, int]]) -> Order:
        customer_reference = customer_reference.strip()
        requested_items = list(items)
        if not customer_reference:
            raise BusinessRuleError("customer reference is required")
        if not requested_items:
            raise BusinessRuleError("an order must contain at least one item")
        if any(quantity <= 0 for _, quantity in requested_items):
            raise BusinessRuleError("item quantities must be positive")

        quantities: dict[int, int] = {}
        for product_id, quantity in requested_items:
            quantities[product_id] = quantities.get(product_id, 0) + quantity

        try:
            self.connection.execute("BEGIN IMMEDIATE")
            products = {}
            for product_id, quantity in quantities.items():
                row = self.connection.execute("SELECT * FROM products WHERE id = ?", (product_id,)).fetchone()
                if row is None:
                    raise BusinessRuleError("product does not exist")
                product = self._product(row)
                if quantity > product.available_quantity:
                    raise BusinessRuleError(f"insufficient stock for {product.name} {product.variant}".strip())
                products[product_id] = product

            total_cents = sum(products[product_id].price_cents * quantity for product_id, quantity in quantities.items())
            cursor = self.connection.execute(
                "INSERT INTO orders (customer_reference, status, total_cents) VALUES (?, ?, ?)",
                (customer_reference, OrderStatus.PENDING.value, total_cents),
            )
            order_id = cursor.lastrowid
            for product_id, quantity in quantities.items():
                product = products[product_id]
                self.connection.execute(
                    "UPDATE products SET reserved_quantity = reserved_quantity + ? WHERE id = ?",
                    (quantity, product_id),
                )
                self.connection.execute(
                    """INSERT INTO order_items
                    (order_id, product_id, product_name, variant, quantity, unit_price_cents)
                    VALUES (?, ?, ?, ?, ?, ?)""",
                    (order_id, product_id, product.name, product.variant, quantity, product.price_cents),
                )
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise
        return self.get_order(order_id)

    def change_order_status(self, order_id: int, new_status: OrderStatus) -> Order:
        order = self.get_order(order_id)
        if new_status not in ALLOWED_STATUS_TRANSITIONS[order.status]:
            raise BusinessRuleError(f"cannot change order from {order.status.value} to {new_status.value}")

        try:
            self.connection.execute("BEGIN IMMEDIATE")
            item_rows = self.connection.execute(
                "SELECT product_id, quantity FROM order_items WHERE order_id = ?", (order_id,)
            ).fetchall()

            # 1. Moving to PACKED: items transition from 'reserved' to 'sold' (physically deducted)
            if new_status == OrderStatus.PACKED:
                for item in item_rows:
                    self.connection.execute(
                        """
                        UPDATE products
                        SET stock_quantity = stock_quantity - ?,
                            reserved_quantity = reserved_quantity - ?
                        WHERE id = ? AND stock_quantity >= ? AND reserved_quantity >= ?
                        """,
                        (item["quantity"], item["quantity"], item["product_id"], item["quantity"], item["quantity"]),
                    )
                    if self.connection.execute("SELECT changes()").fetchone()[0] != 1:
                        raise BusinessRuleError("stock or reservation is inconsistent")

            # 2. Moving to CANCELLED: return items to available inventory
            elif new_status == OrderStatus.CANCELLED:
                if order.status == OrderStatus.PENDING:
                    # Items were only reserved: release the reservation back to available
                    for item in item_rows:
                        self.connection.execute(
                            """
                            UPDATE products 
                            SET reserved_quantity = reserved_quantity - ? 
                            WHERE id = ? AND reserved_quantity >= ?
                            """,
                            (item["quantity"], item["product_id"], item["quantity"]),
                        )
                        if self.connection.execute("SELECT changes()").fetchone()[0] != 1:
                            raise BusinessRuleError("reserved stock is inconsistent")
                else:
                    # Order was PACKED or SHIPPED: stock was physically deducted, so add it back to inventory
                    for item in item_rows:
                        self.connection.execute(
                            "UPDATE products SET stock_quantity = stock_quantity + ? WHERE id = ?",
                            (item["quantity"], item["product_id"]),
                        )

            # Update the order status
            self.connection.execute("UPDATE orders SET status = ? WHERE id = ? AND status = ?",
                                    (new_status.value, order_id, order.status.value))
            if self.connection.execute("SELECT changes()").fetchone()[0] != 1:
                raise BusinessRuleError("order status changed concurrently; refresh and retry")
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise

        return self.get_order(order_id)

    def _product(self, row: sqlite3.Row) -> Product:
        sold = row["sold_quantity"] if "sold_quantity" in row.keys() else 0
        return Product(
            id=row["id"],
            name=row["name"],
            variant=row["variant"],
            price_cents=row["price_cents"],
            stock_quantity=row["stock_quantity"],
            reserved_quantity=row["reserved_quantity"],
            sold_quantity=sold,
        )

    def _order(self, row: sqlite3.Row) -> Order:
        item_rows = self.connection.execute(
            "SELECT product_id, product_name, variant, quantity, unit_price_cents FROM order_items WHERE order_id = ? ORDER BY id",
            (row["id"],),
        ).fetchall()
        items = tuple(OrderItem(item["product_id"], item["product_name"], item["variant"], item["quantity"], item["unit_price_cents"]) for item in item_rows)
        return Order(row["id"], row["customer_reference"], OrderStatus(row["status"]), row["total_cents"], row["created_at"], items)
