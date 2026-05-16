from __future__ import annotations

import csv
import os
import time
from datetime import datetime, timezone

_LOG_INTERVAL = 1.0  # seconds between log entries
_LOG_DIR = os.path.join(os.path.dirname(__file__), "..", "logs")


class GpsLogger:
    def __init__(self, log_dir: str = _LOG_DIR, interval: float = _LOG_INTERVAL):
        self._interval = interval
        self._last_log = 0.0
        self._file = None
        self._writer = None
        self._open(log_dir)

    def _open(self, log_dir: str) -> None:
        try:
            os.makedirs(log_dir, exist_ok=True)
            ts = datetime.now().strftime("%Y-%m-%d_%H%M%S")
            path = os.path.join(log_dir, f"gps_{ts}.csv")
            self._file = open(path, "w", newline="", buffering=1)
            self._writer = csv.writer(self._file)
            self._writer.writerow(["timestamp", "latitude", "longitude", "speed_kph", "satellites"])
        except Exception as e:
            print(f"GpsLogger: could not open log file: {e}")

    def tick(self, gps_state) -> None:
        if self._writer is None:
            return
        now = time.monotonic()
        if now - self._last_log < self._interval:
            return
        self._last_log = now
        if not gps_state.fix_valid:
            return
        ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
        try:
            self._writer.writerow([
                ts,
                f"{gps_state.latitude:.7f}",
                f"{gps_state.longitude:.7f}",
                f"{gps_state.speed_kph:.2f}",
                gps_state.satellites,
            ])
        except Exception:
            pass

    def close(self) -> None:
        try:
            if self._file:
                self._file.close()
        except Exception:
            pass
