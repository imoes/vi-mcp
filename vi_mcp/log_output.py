"""Server log output — one line per event on stderr (systemd → journal)."""
import sys
from datetime import datetime, timezone


def log(msg: str) -> None:
    print(f"{datetime.now(timezone.utc).isoformat(timespec='seconds')} vi-mcp: {msg}", file=sys.stderr, flush=True)
