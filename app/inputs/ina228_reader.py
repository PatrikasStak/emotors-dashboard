from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Optional


CAL_REG = 0x02
BUS_VOLT_REG = 0x05
CURRENT_REG = 0x07


@dataclass
class INA228State:
    last_update: float = 0.0
    voltage_v: float = 0.0
    current_a: float = 0.0


class INA228Reader:
    def __init__(
        self,
        bus: int = 1,
        address: int = 0x40,
        shunt_ohms: float = 0.00075,
        current_lsb: float = 0.003,
        debug: bool = False,
    ):
        self.bus = bus
        self.address = address
        self.shunt_ohms = shunt_ohms
        self.current_lsb = current_lsb
        self.debug = debug

        self._t: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._s = INA228State()
        self._dbg_next = 0.0
        self._bus = None

    def start(self) -> None:
        self._t = threading.Thread(target=self._run, daemon=True)
        self._t.start()

    def stop(self) -> None:
        self._stop.set()
        if self._t:
            self._t.join(timeout=1.0)

    def snapshot(self) -> INA228State:
        with self._lock:
            return INA228State(**self._s.__dict__)

    def _open_bus(self):
        try:
            from smbus2 import SMBus
            return SMBus(self.bus)
        except Exception as e:
            if self.debug:
                print(f"INA228 SMBus open failed: {e}")
            return None

    def _write_u16_be(self, reg: int, value: int) -> None:
        if not self._bus:
            return
        v = value & 0xFFFF
        swapped = ((v & 0xFF) << 8) | ((v >> 8) & 0xFF)
        self._bus.write_word_data(self.address, reg, swapped)

    def _read_u16_be(self, reg: int) -> int:
        if not self._bus:
            return 0
        raw = self._bus.read_word_data(self.address, reg)
        return ((raw & 0xFF) << 8) | ((raw >> 8) & 0xFF)

    def _read_s16_be(self, reg: int) -> int:
        v = self._read_u16_be(reg)
        if v & 0x8000:
            v -= 0x10000
        return v

    def _write_calibration(self) -> None:
        # INA-style calibration formula using requested LSB + shunt
        if self.current_lsb <= 0 or self.shunt_ohms <= 0:
            return
        cal = int(0.00512 / (self.current_lsb * self.shunt_ohms))
        cal = max(0, min(0xFFFF, cal))
        self._write_u16_be(CAL_REG, cal)

    def _update(self, voltage_v: float, current_a: float) -> None:
        now = time.monotonic()
        with self._lock:
            self._s.last_update = now
            self._s.voltage_v = voltage_v
            self._s.current_a = current_a

    def _run(self) -> None:
        while not self._stop.is_set():
            if self._bus is None:
                self._bus = self._open_bus()
                if self._bus is None:
                    time.sleep(1.0)
                    continue
                try:
                    self._write_calibration()
                except Exception as e:
                    if self.debug:
                        print(f"INA228 calibration failed: {e}")

            try:
                raw_bus = self._read_u16_be(BUS_VOLT_REG)
                raw_current = self._read_s16_be(CURRENT_REG)

                voltage_v = raw_bus * 0.003125
                current_a = raw_current * self.current_lsb

                self._update(voltage_v, current_a)

                now = time.monotonic()
                if self.debug and now >= self._dbg_next:
                    self._dbg_next = now + 1.0
                    s = self.snapshot()
                    print(f"DBG ina228 V={s.voltage_v:.2f}V I={s.current_a:.2f}A")

                time.sleep(0.1)
            except Exception as e:
                if self.debug:
                    now = time.monotonic()
                    if now >= self._dbg_next:
                        self._dbg_next = now + 1.0
                        print(f"DBG ina228 read error: {e}")
                try:
                    if self._bus:
                        self._bus.close()
                except Exception:
                    pass
                self._bus = None
                time.sleep(0.2)
