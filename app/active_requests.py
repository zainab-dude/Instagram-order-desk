"""Pure ASGI middleware: HTTP active-request gauge and the A3 injected delay.

Added immediately after FastAPI(...) so it is the innermost user middleware: the delay is
therefore inside the existing http_request_duration_seconds measurement.
"""
import asyncio

from .metrics import HTTP_ACTIVE_REQUESTS
from .replica import injected_delay_seconds

# Health checks and Prometheus scrapes are not application traffic: they are neither
# counted as active requests nor delayed (so a slow replica still passes health checks).
EXCLUDED_PATHS = {"/health", "/metrics"}


class ActiveRequestsMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope.get("path") in EXCLUDED_PATHS:
            await self.app(scope, receive, send)
            return
        HTTP_ACTIVE_REQUESTS.inc()
        try:
            delay = injected_delay_seconds()
            if delay > 0:
                await asyncio.sleep(delay)
            await self.app(scope, receive, send)
        finally:
            HTTP_ACTIVE_REQUESTS.dec()
