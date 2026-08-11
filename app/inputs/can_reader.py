from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Optional

import can

ID_E05 = 0x0CF11E05
ID_F05 = 0x0CF11F05


def u16_le(lo: int, hi: int) -> int:
    return ((hi & 0xFF) << 8) | (lo & 0xFF)


@dataclass
class CANState:
    bus_last_update: float = 0.0
    rpm: float = 0.0
    battery_voltage_v: float = 0.0
    dc_current_a: float = 0.0
    switch_value_v: float = 0.0

    # extra decoded fields (optional for debug/UI)
    motor_current_a: float = 0.0
    throttle_v: float = 0.0
    controller_temp_c: int = 0
    motor_temp_c: int = 0
    error_code: int = 0
    brake_on: bool = False
    reverse_active: bool = False
    command_state: int = 1  # raw "Status of command" bits: 0=Neutral, 1=forward, 2=backward


class CANReader:
    def __init__(self, channel: str = "can0", debug: bool = False):
        self.channel = channel
        self.debug = debug
        self._bus: Optional[can.Bus] = None
        self._t: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._s = CANState()
        self._dbg_next = 0.0

    def start(self) -> None:
        filters = [
            {"can_id": ID_E05, "can_mask": 0x1FFFFFFF, "extended": True},
            {"can_id": ID_F05, "can_mask": 0x1FFFFFFF, "extended": True},
        ]
        self._bus = can.interface.Bus(
            channel=self.channel, interface="socketcan", can_filters=filters
        )
        self._t = threading.Thread(target=self._run, daemon=True)
        self._t.start()

    def stop(self) -> None:
        self._stop.set()
        if self._t:
            self._t.join(timeout=1.0)
        if self._bus:
            try:
                self._bus.shutdown()
            except Exception:
                pass

    def snapshot(self) -> CANState:
        with self._lock:
            return CANState(**self._s.__dict__)

    def _run(self) -> None:
        assert self._bus is not None

        while not self._stop.is_set():
            msg = self._bus.recv(timeout=1.0)
            if msg is None:
                continue
            if not msg.is_extended_id:
                continue

            d = bytes(msg.data)
            if len(d) < 8:
                continue

            now = time.monotonic()
            can_id = msg.arbitration_id

            with self._lock:
                self._s.bus_last_update = now

            if can_id == ID_E05:
                rpm = float(u16_le(d[0], d[1]))
                cur = float(u16_le(d[2], d[3])) / 10.0
                volt = float(u16_le(d[4], d[5])) / 10.0
                err = (d[7] << 8) | d[6]

                with self._lock:
                    self._s.rpm = rpm
                    self._s.dc_current_a = cur
                    self._s.motor_current_a = cur
                    self._s.battery_voltage_v = volt
                    self._s.error_code = err

            elif can_id == ID_F05:
                throttle_v = (d[0] / 255.0) * 5.0
                controller_temp_c = int(d[1]) - 40
                motor_temp_c = int(d[2]) - 30
                brake_on = (d[5] & 0x08) != 0
                cmd = d[4] & 0x03
                reverse_active = (cmd == 0x02)

                with self._lock:
                    self._s.switch_value_v = throttle_v
                    self._s.throttle_v = throttle_v
                    self._s.controller_temp_c = controller_temp_c
                    self._s.motor_temp_c = motor_temp_c
                    self._s.brake_on = brake_on
                    self._s.reverse_active = reverse_active
                    self._s.command_state = cmd

            if self.debug and now >= self._dbg_next:
                self._dbg_next = now + 1.0
                s = self.snapshot()
                print(
                    f"DBG rpm={s.rpm:.0f} V={s.battery_voltage_v:.1f} "
                    f"I={s.dc_current_a:.1f} thr={s.switch_value_v:.2f} "
                    f"Tctl={s.controller_temp_c} Tmot={s.motor_temp_c} "
                    f"err=0x{s.error_code:04X}"
                )
