import json
import logging
import sys
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any


REQUEST_ID: ContextVar[str] = ContextVar("request_id", default="-")
LOGGER_NAME = "observable_orders"


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        event = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "service": {"name": "instagram-order-desk"},
            "severity": record.levelname,
            "message": record.getMessage(),
            "request_id": getattr(record, "request_id", REQUEST_ID.get()),
        }
        for field in ("order_id", "product_id", "status", "old_status", "new_status", "method", "path", "status_code", "duration_ms", "error_type"):
            value = getattr(record, field, None)
            if value is not None:
                event[field] = value
        return json.dumps(event, separators=(",", ":"), sort_keys=True)


def get_logger() -> logging.Logger:
    logger = logging.getLogger(LOGGER_NAME)
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(JsonFormatter())
        logger.addHandler(handler)
        logger.propagate = False
        logger.setLevel(logging.INFO)
    return logger


def log_event(level: int, message: str, **fields: Any) -> None:
    get_logger().log(level, message, extra={"request_id": REQUEST_ID.get(), **fields})