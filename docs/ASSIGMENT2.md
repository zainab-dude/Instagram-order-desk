# Assignment 2 scope

**User task:** Place an order

| Version | Operation | Where it lives |
|---|---|---|
| HTTP | `POST /api/orders` | FastAPI app (container: `app`) |
| gRPC | `OrderService.CreateOrder` | New container: `grpc-service` |

- Both versions call the same shared function: `app/order_services.py` → `place_order()`.
- Business rules live in `Store.create_order_idempotent()` in `app/services.py`.
- Both use the same SQLite database (`app-data` volume).
- **Idempotency:** `Idempotency-Key` header on `POST /api/orders`.
- **Rate limit:** `POST /api/orders` only, 5 requests per 10 seconds per client IP.
- **Error format:** `{"error": {"code": "...", "message": "..."}}`.