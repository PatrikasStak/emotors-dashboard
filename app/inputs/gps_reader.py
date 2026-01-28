# app/inputs/gps_reader.py
from __future__ import annotations
import threading, time
from dataclasses import dataclass, field
from typing import Optional

import gpsd

@dataclass
class GPSState:
    speed_kph: float = 0.0
    has_fix: bool = False
    last_update: float = field(default_factory=lambda: 0.0)  # 0 = never

class GPSReader:
    def __init__(self):
        self._t: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._state = GPSState()
        self._connected = False

    def start(self) -> None:
        self._t = threading.Thread(target=self._run, daemon=True)
        self._t.start()

    def stop(self) -> None:
        self._stop.set()
        if self._t:
            self._t.join(timeout=1.0)

    def snapshot(self) -> GPSState:
        with self._lock:
            return GPSState(**self._state.__dict__)

    def _try_connect(self) -> None:
        if self._connected:
            return
        try:
            gpsd.connect()
            self._connected = True
        except Exception:
            self._connected = False

    def _run(self) -> None:
        while not self._stop.is_set():
            self._try_connect()

            if self._connected:
                try:
                    p = gpsd.get_current()
                    speed_mps = p.speed() or 0.0
                    speed_kph = float(speed_mps) * 3.6
                    has_fix = bool(getattr(p, "mode", 0) and p.mode >= 2)

                    with self._lock:
                        self._state.speed_kph = speed_kph
                        self._state.has_fix = has_fix
                        self._state.last_update = time.monotonic()
                except Exception:
                    # device disappeared / gpsd unhappy; retry connect
                    self._connected = False

            time.sleep(0.25)
