"""Replica identity and the A3 per-replica delay control (Part D, least-request experiment)."""
import os
from pathlib import Path

REPLICA_ID = os.getenv("REPLICA_ID", "")
DELAY_FILE = Path(os.getenv("DELAY_FILE", "/app/control/delay_ms"))


def injected_delay_seconds() -> float:
    """Delay in seconds read from DELAY_FILE (milliseconds). Missing, empty or invalid means 0.

    Read on every call so the delay can be changed without restarting the replica.
    """
    try:
        value = int(DELAY_FILE.read_text(encoding="utf-8").strip() or "0")
    except (OSError, ValueError):
        return 0.0
    return max(0, value) / 1000
