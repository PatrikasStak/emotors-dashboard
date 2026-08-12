from __future__ import annotations

import json
import os
import time
from collections import deque

_DEFAULT_PATH = os.path.join(os.path.dirname(__file__), "..", "range_state.json")
_SAVE_INTERVAL = 10.0  # seconds between auto-saves

_EFFICIENCY_WINDOW_SEC = 180.0  # rolling window for the Wh/km efficiency average
_MOVING_SPEED_MIN_KPH = 1.0     # ignore near-zero speed so idling doesn't skew efficiency

_POWER_WINDOW_SEC = 60.0  # rolling window for the average-power (time remaining) estimate

_REST_CURRENT_MAX_A = 1.0    # "at rest" (no load) threshold for OCV recalibration
_REST_DURATION_SEC = 90.0    # how long it must stay at rest before trusting OCV

# Generic Li-ion (NMC/LCO) rest-voltage SOC curve, per cell. Flat through the
# middle and steep near the ends - voltage alone is a poor real-time SOC signal
# (which is why this is only used to recalibrate Coulomb counting at rest, not
# read directly during normal operation).
CELL_OCV_SOC = [
    (3.00, 0.0), (3.68, 10.0), (3.73, 20.0), (3.77, 30.0),
    (3.79, 40.0), (3.82, 50.0), (3.87, 60.0), (3.92, 70.0),
    (3.98, 80.0), (4.06, 90.0), (4.20, 100.0),
]


def _voltage_to_soc(cell_voltage: float, table: list) -> float:
    if cell_voltage <= table[0][0]:
        return table[0][1]
    if cell_voltage >= table[-1][0]:
        return table[-1][1]
    for i in range(len(table) - 1):
        v0, s0 = table[i]
        v1, s1 = table[i + 1]
        if v0 <= cell_voltage <= v1:
            t = (cell_voltage - v0) / (v1 - v0)
            return s0 + t * (s1 - s0)
    return table[-1][1]


class RangeEstimator:
    """
    Projects remaining range like an EV does: Coulomb-counts the pack's remaining
    capacity from measured current draw (not a fixed physics model), periodically
    recalibrated from rest voltage, then divides by a rolling Wh/km efficiency
    average built from actual recent driving.

    Stays inert (range_km/soc_pct == None) until capacity_ah is known.
    """

    def __init__(self, capacity_ah: float | None, series_cells: int, path: str = _DEFAULT_PATH):
        self.capacity_ah = capacity_ah
        self.series_cells = series_cells
        self.path = os.path.abspath(path)

        self._remaining_ah = capacity_ah or 0.0
        self._last_tick = 0.0
        self._last_save = 0.0
        self._rest_since = 0.0

        self._energy_wh_samples: deque = deque()   # (t, wh_used_in_step)
        self._distance_km_samples: deque = deque()  # (t, km_traveled_in_step)
        self._power_kw_samples: deque = deque()     # (t, power_kw) - not gated by movement

        self.range_km: float | None = None
        self.range_hours: float | None = None
        self.soc_pct: float | None = None

        self._load()

    def _load(self) -> None:
        if not self.capacity_ah:
            return
        try:
            with open(self.path) as f:
                d = json.load(f)
            self._remaining_ah = float(d.get("remaining_ah", self._remaining_ah))
        except Exception:
            pass

    def save(self) -> None:
        if not self.capacity_ah:
            return
        try:
            tmp = self.path + ".tmp"
            with open(tmp, "w") as f:
                json.dump({"remaining_ah": self._remaining_ah}, f, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, self.path)
        except Exception:
            pass

    def reset_full(self) -> None:
        """Call when the pack has just been charged to 100%."""
        if self.capacity_ah:
            self._remaining_ah = self.capacity_ah
            self.save()

    def tick(self, current_a: float, voltage_v: float, speed_kph: float) -> None:
        now = time.monotonic()
        if self._last_tick == 0.0:
            self._last_tick = now
            return
        dt = now - self._last_tick
        self._last_tick = now
        dt_hours = dt / 3600.0

        if self.capacity_ah:
            # Coulomb counting: positive current draws the pack down.
            self._remaining_ah -= current_a * dt_hours
            self._remaining_ah = max(0.0, min(self.capacity_ah, self._remaining_ah))

            # Recalibrate from rest (open-circuit) voltage once settled, to correct drift.
            if abs(current_a) <= _REST_CURRENT_MAX_A:
                if self._rest_since == 0.0:
                    self._rest_since = now
                elif now - self._rest_since >= _REST_DURATION_SEC and voltage_v > 0.0:
                    cell_v = voltage_v / self.series_cells
                    soc = _voltage_to_soc(cell_v, CELL_OCV_SOC)
                    self._remaining_ah = self.capacity_ah * (soc / 100.0)
            else:
                self._rest_since = 0.0

            self.soc_pct = (self._remaining_ah / self.capacity_ah) * 100.0
        else:
            self.soc_pct = None

        # Rolling energy-per-distance efficiency window (only while actually moving).
        power_kw = (voltage_v * current_a) / 1000.0
        wh_used = power_kw * dt_hours * 1000.0
        km_traveled = speed_kph * dt_hours

        if speed_kph >= _MOVING_SPEED_MIN_KPH:
            self._energy_wh_samples.append((now, wh_used))
            self._distance_km_samples.append((now, km_traveled))
        cutoff = now - _EFFICIENCY_WINDOW_SEC
        while self._energy_wh_samples and self._energy_wh_samples[0][0] < cutoff:
            self._energy_wh_samples.popleft()
        while self._distance_km_samples and self._distance_km_samples[0][0] < cutoff:
            self._distance_km_samples.popleft()

        total_wh = sum(v for _, v in self._energy_wh_samples)
        total_km = sum(v for _, v in self._distance_km_samples)

        if self.capacity_ah and total_km > 0.05 and total_wh > 0.0:
            wh_per_km = total_wh / total_km
            remaining_wh = self._remaining_ah * voltage_v
            self.range_km = remaining_wh / wh_per_km
        else:
            self.range_km = None

        # Rolling average power draw (any load counts, not just while moving).
        self._power_kw_samples.append((now, power_kw))
        power_cutoff = now - _POWER_WINDOW_SEC
        while self._power_kw_samples and self._power_kw_samples[0][0] < power_cutoff:
            self._power_kw_samples.popleft()
        avg_power_kw = sum(v for _, v in self._power_kw_samples) / len(self._power_kw_samples)

        if self.capacity_ah and avg_power_kw > 0.05:
            remaining_wh = self._remaining_ah * voltage_v
            self.range_hours = (remaining_wh / 1000.0) / avg_power_kw
        else:
            self.range_hours = None

        if now - self._last_save >= _SAVE_INTERVAL:
            self.save()
            self._last_save = now
