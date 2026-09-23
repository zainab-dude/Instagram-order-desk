"""Local Part E experiment only. No HTTP switch and no default activation."""

import asyncio
import os
import time
from pathlib import Path

from .logging_config import log_event


class OrderLatencyFault:
    TOKEN = "ENABLE_500MS_EVERY_5TH"
    MAX_AGE_SECONDS = 300
    CONTROL_FILE = Path("/app/experiment-control/latency.txt")

    def __init__(self):
        # Captured at startup: a file or request alone cannot enable this fault.
        self.armed = os.getenv("PART_E_TEST_MODE") == "controlled-local-only"
        self.sequence = 0

    async def before_request(self, method: str, path: str) -> None:
        if not self.armed or method != "POST" or path != "/api/orders":
            return
        try:
            age = time.time() - self.CONTROL_FILE.stat().st_mtime
            enabled = (
                0 <= age <= self.MAX_AGE_SECONDS
                and self.CONTROL_FILE.read_text(encoding="utf-8").strip() == self.TOKEN
            )
        except OSError:
            enabled = False  # Missing/unreadable control file fails closed.
        if not enabled:
            self.sequence = 0
            return
        # No await between increment and decision: single event-loop process.
        self.sequence += 1
        if self.sequence % 5 == 0:
            log_event(30, "test-only order latency injected", duration_ms=500)
            await asyncio.sleep(0.5)  # Yield the event loop; do not burn CPU.
