from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Optional

import can

# Kelly KLS broadcast IDs (extended 29-bit)
KELLY_MSG1 = 0x0CF11E05  # RPM, motor current, battery voltage, error bits
KELLY_MSG2 = 0x0CF11F05  # throttle, temps, status/switch bytes


@dataclass
class CANState:
    rpm: float = 0.0
    motor_current_a: float = 0.0
    battery_voltage_v: float = 0.0
    error_bits: int = 0

    throttle_raw: int = 0
    controller_temp_c: float = 0.0
    motor_temp_c: float = 0.0
    status_controller: int = 0
    status_switches: int = 0

    last_update: float = field(default_factory=time.monotonic)


def _u16_le(data: bytes, off: int) -> int:
    return int.from_bytes(data[off:off + 2], "little", signed=False)


def _s16_le(data: bytes, off: int) -> int:
    return int.from_bytes(data[off:off + 2], "little", signed=True)


class CANReader:
    def __init__(self, channel: str = "can0"):
        self.channel = channel
        self._bus: Optional[can.Bus] = None
        self._t: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._state = CANState()

    def start(self) -> None:
        self._bus = can.interface.Bus(channel=self.channel, bustype="socketcan")

        # Filter only the IDs we care about (reduces CPU)
        try:
            self._bus.set_filters([
                {"can_id": KELLY_MSG1, "can_mask": 0x1FFFFFFF, "extended": True},
                {"can_id": KELLY_MSG2, "can_mask": 0x1FFFFFFF, "extended": True},
            ])
        except Exception:
            pass

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
            return CANState(**self._state.__dict__)

    def _run(self) -> None:
        assert self._bus is not None
        while not self._stop.is_set():
            msg = self._bus.recv(timeout=0.5)
            if msg is None:
                continue

            can_id = msg.arbitration_id
            data = bytes(msg.data)
            if len(data) < 8:
                continue

            updated = False

            if can_id == KELLY_MSG1:
                rpm = _u16_le(data, 0) * 1.0
                motor_current_a = _s16_le(data, 2) / 10.0
                battery_voltage_v = _u16_le(data, 4) / 10.0
                error_bits = _u16_le(data, 6)

                with self._lock:
                    self._state.rpm = rpm
                    self._state.motor_current_a = motor_current_a
                    self._state.battery_voltage_v = battery_voltage_v
                    self._state.error_bits = int(error_bits)
                updated = True

            elif can_id == KELLY_MSG2:
                throttle_raw = data[0]
                controller_temp_c = int(data[1]) - 40
                motor_temp_c = int(data[2]) - 30
                status_controller = data[4]
                status_switches = data[5]

                with self._lock:
                    self._state.throttle_raw = int(throttle_raw)
                    self._state.controller_temp_c = float(controller_temp_c)
                    self._state.motor_temp_c = float(motor_temp_c)
                    self._state.status_controller = int(status_controller)
                    self._state.status_switches = int(status_switches)
                updated = True

            if updated:
                with self._lock:
                    self._state.last_update = time.monotonic()
