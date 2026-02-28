from __future__ import annotations

import threading, time
from dataclasses import dataclass
from typing import Optional

import can

ID_6E4 = 0x6E4
ID_6E5 = 0x6E5

PAGE_RPM = 0x59
PAGE_PWR = 0x24
PAGE_SW  = 0x12
PAGE_TMP = 0x2C


def u16_le(lo: int, hi: int) -> int:
    return ((hi & 0xFF) << 8) | (lo & 0xFF)

def u16_be(hi: int, lo: int) -> int:
    return ((hi & 0xFF) << 8) | (lo & 0xFF)

def i16_le(lo: int, hi: int) -> int:
    u = u16_le(lo, hi)
    return u - 0x10000 if (u & 0x8000) else u

def ema(prev: float, new: float, a: float) -> float:
    return new if prev == 0.0 else (prev * (1.0 - a) + new * a)


@dataclass
class CANState:
    bus_last_update: float = 0.0

    rpm: float = 0.0
    battery_voltage_v: float = 0.0
    dc_current_a: float = 0.0
    switch_value_v: float = 0.0

    rpm_last: float = 0.0
    pwr_last: float = 0.0
    switch_last: float = 0.0
    temps_last: float = 0.0


class CANReader:
    # smoothing
    A_SW  = 0.22
    A_RPM = 0.25
    A_V   = 0.18
    A_I   = 0.18

    # switch decode
    SWITCH_DIV  = 4096.0
    SWITCH_GAIN = 1.40

    # power decode
    VOLT_DIV = 1000.0
    CURR_DIV = 100.0

    # thresholds / guards
    IDLE_SW_V_THRESH = 0.90

    V_MIN = 10.0
    V_MAX = 70.0
    MAX_V_STEP_PER_SEC = 8.0    # allows sag, blocks jumps

    MAX_RPM_JUMP = 2500.0
    RPM_MAX = 7000.0

    def __init__(self, channel: str = "can0", debug: bool = False):
        self.channel = channel
        self.debug = debug

        self._bus: Optional[can.Bus] = None
        self._t: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._s = CANState()

        # baselines (LOCK ONCE)
        self._rpm_zero: Optional[float] = None
        self._rpm_acc = 0.0
        self._rpm_n = 0

        self._i_zero: Optional[float] = None
        self._i_acc = 0.0
        self._i_n = 0

        self._dbg_next = 0.0

    def start(self) -> None:
        filters = [
            {"can_id": ID_6E4, "can_mask": 0x7FF, "extended": False},
            {"can_id": ID_6E5, "can_mask": 0x7FF, "extended": False},
        ]
        self._bus = can.interface.Bus(channel=self.channel, interface="socketcan", can_filters=filters)
        self._t = threading.Thread(target=self._run, daemon=True)
        self._t.start()

    def stop(self) -> None:
        self._stop.set()
        if self._t:
            self._t.join(timeout=1.0)
        if self._bus:
            try: self._bus.shutdown()
            except Exception: pass

    def snapshot(self) -> CANState:
        with self._lock:
            return CANState(**self._s.__dict__)

    def _rate_ok(self, prev: float, new: float, last_t: float, now: float, max_per_sec: float) -> bool:
        if prev == 0.0 or last_t == 0.0:
            return True
        dt = max(0.01, now - last_t)
        return abs(new - prev) <= max_per_sec * dt

    def _run(self) -> None:
        assert self._bus is not None

        while not self._stop.is_set():
            msg = self._bus.recv(timeout=1.0)
            if msg is None:
                continue

            d = bytes(msg.data)
            if len(d) < 8:
                continue

            now = time.monotonic()
            can_id = msg.arbitration_id & 0x7FF
            page = d[0]

            with self._lock:
                self._s.bus_last_update = now

            # --- switch/throttle ---
            if can_id == ID_6E5 and page == PAGE_SW:
                raw = u16_le(d[1], d[2])
                sv = (raw / self.SWITCH_DIV) * self.SWITCH_GAIN
                if not (0.0 <= sv <= 5.2):
                    continue
                with self._lock:
                    self._s.switch_value_v = ema(self._s.switch_value_v, sv, self.A_SW)
                    self._s.switch_last = now

            # --- power (voltage/current) ---
            elif can_id == ID_6E4 and page == PAGE_PWR:
                raw_v = u16_le(d[1], d[2])
                raw_i = i16_le(d[6], d[7])

                v = float(raw_v) / self.VOLT_DIV
                if not (self.V_MIN <= v <= self.V_MAX):
                    continue

                with self._lock:
                    prev_v = self._s.battery_voltage_v
                    v_last = self._s.pwr_last
                    sw = self._s.switch_value_v

                if not self._rate_ok(prev_v, v, v_last, now, self.MAX_V_STEP_PER_SEC):
                    continue

                # current baseline only at idle, lock once-ish (keeps idle amps stable)
                if sw < self.IDLE_SW_V_THRESH:
                    self._i_acc += float(raw_i)
                    self._i_n += 1
                    if self._i_n >= 250 and self._i_zero is None:
                        self._i_zero = self._i_acc / self._i_n

                i = (float(raw_i) - (self._i_zero if self._i_zero is not None else float(raw_i))) / self.CURR_DIV
                if abs(i) > 400.0:
                    continue

                with self._lock:
                    self._s.battery_voltage_v = ema(self._s.battery_voltage_v, v, self.A_V)
                    self._s.dc_current_a = ema(self._s.dc_current_a, i, self.A_I)
                    self._s.pwr_last = now

            # --- rpm ---
            elif can_id == ID_6E4 and page == PAGE_RPM:
                # Gate on the common header for the "real" rpm group seen in your logs:
                # 59 08 84 42 ...
                if not (d[1] == 0x08 and d[2] == 0x84 and d[3] == 0x42):
                    continue

                # RPM candidate that behaves best in your spin log:
                raw = u16_be(d[1], d[2]) / 2.0  # maps into ~0..7000 range

                with self._lock:
                    sw = self._s.switch_value_v
                    prev_rpm = self._s.rpm

                # lock rpm zero ONCE after ~1–2s of idle
                if sw < self.IDLE_SW_V_THRESH and self._rpm_zero is None:
                    self._rpm_acc += raw
                    self._rpm_n += 1
                    if self._rpm_n >= 250:
                        self._rpm_zero = self._rpm_acc / self._rpm_n

                rpm = raw - (self._rpm_zero if self._rpm_zero is not None else raw)
                rpm = max(0.0, min(self.RPM_MAX, rpm))

                if prev_rpm != 0.0 and abs(rpm - prev_rpm) > self.MAX_RPM_JUMP:
                    continue

                with self._lock:
                    self._s.rpm = ema(self._s.rpm, rpm, self.A_RPM)
                    self._s.rpm_last = now

            elif can_id == ID_6E5 and page == PAGE_TMP:
                with self._lock:
                    self._s.temps_last = now

            if self.debug and now >= self._dbg_next:
                self._dbg_next = now + 1.0
                s = self.snapshot()
                print(f"DBG sw={s.switch_value_v:.2f} rpm={s.rpm:.0f} V={s.battery_voltage_v:.2f} I={s.dc_current_a:.1f} rpm0={self._rpm_zero} i0={self._i_zero}")
