from __future__ import annotations

import csv
import os
import shutil
import time
from datetime import datetime, timezone

_LOG_INTERVAL = 1.0  # seconds between log entries
_LOG_PATH = os.path.join(os.path.dirname(__file__), "..", "logs", "gps.csv")
_HEADER = [
    "timestamp", "latitude", "longitude", "speed_kph", "satellites",
    "rpm", "power_kw", "dc_current_a", "ac_current_a",
    "battery_voltage_v", "joystick_voltage_v", "borto_raw_v", "thruster_raw_v",
    "errors",
]


class GpsLogger:
    def __init__(self, path: str = _LOG_PATH, interval: float = _LOG_INTERVAL):
        self._path = os.path.abspath(path)
        self._interval = interval
        self._last_log = 0.0
        self._file = None
        self._writer = None
        self._open()

    def _open(self) -> None:
        try:
            os.makedirs(os.path.dirname(self._path), exist_ok=True)
            new_file = not os.path.exists(self._path)
            self._file = open(self._path, "a", newline="", buffering=1)
            self._writer = csv.writer(self._file)
            if new_file:
                self._writer.writerow(_HEADER)
        except Exception as e:
            print(f"GpsLogger: could not open log file: {e}")

    def tick(self, state, gps_state) -> None:
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
                f"{state.rpm:.0f}",
                f"{state.power_kw:.2f}",
                f"{state.dc_current_a:.1f}",
                f"{state.ac_current_a:.1f}",
                f"{state.battery_voltage_v:.1f}",
                f"{state.switch_value_v:.2f}",
                f"{state.borto_raw_v:.3f}",
                f"{state.thruster_raw_v:.3f}",
                "|".join(state.errors) if state.errors else "",
            ])
        except Exception:
            pass

    def export_and_clear(self, dest_dir: str) -> None:
        try:
            self.close()
            if os.path.exists(self._path):
                ts = datetime.now().strftime("%Y-%m-%d_%H%M%S")
                dest = os.path.join(dest_dir, f"gps_{ts}.csv")
                shutil.copy2(self._path, dest)
                with open(self._path, "w", newline="") as f:
                    csv.writer(f).writerow(_HEADER)
        except Exception as e:
            print(f"GpsLogger export error: {e}")
        finally:
            self._open()

    def close(self) -> None:
        try:
            if self._file:
                self._file.close()
                self._file = None
                self._writer = None
        except Exception:
            pass
