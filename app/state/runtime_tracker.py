from __future__ import annotations

import json
import os
import time

_DEFAULT_PATH = os.path.join(os.path.dirname(__file__), "..", "runtime.json")
_SAVE_INTERVAL = 10.0  # seconds between auto-saves


def _fmt(seconds: float) -> str:
    s = int(seconds)
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    return f"{h}:{m:02d}:{sec:02d}"


class RuntimeTracker:
    def __init__(self, path: str = _DEFAULT_PATH):
        self.path = os.path.abspath(path)
        self._trip_s = 0.0
        self._total_s = 0.0
        self._lifetime_s = 0.0
        self._last_save = 0.0
        self._load()

    def _load(self) -> None:
        try:
            with open(self.path) as f:
                d = json.load(f)
            self._trip_s = float(d.get("trip_s", 0.0))
            self._total_s = float(d.get("total_s", 0.0))
            self._lifetime_s = float(d.get("lifetime_s", 0.0))
        except Exception:
            pass

    def save(self) -> None:
        try:
            tmp = self.path + ".tmp"
            with open(tmp, "w") as f:
                json.dump({
                    "trip_s": self._trip_s,
                    "total_s": self._total_s,
                    "lifetime_s": self._lifetime_s,
                }, f, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, self.path)
        except Exception:
            pass

    def tick(self, dt: float, counting: bool) -> None:
        if counting:
            self._trip_s += dt
            self._total_s += dt
            self._lifetime_s += dt
        now = time.monotonic()
        if now - self._last_save >= _SAVE_INTERVAL:
            self.save()
            self._last_save = now

    def reset_trip(self) -> None:
        self._trip_s = 0.0

    def reset_total(self) -> None:
        self._trip_s = 0.0
        self._total_s = 0.0

    @property
    def total_hours(self) -> float:
        return self._total_s / 3600.0

    @property
    def trip_str(self) -> str:
        return _fmt(self._trip_s)

    @property
    def total_str(self) -> str:
        return _fmt(self._total_s)

    @property
    def lifetime_hours(self) -> float:
        return self._lifetime_s / 3600.0

    @property
    def lifetime_str(self) -> str:
        return _fmt(self._lifetime_s)
