from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Optional

_MA_WINDOW = 10   # moving average window size
_MIN_V     = 1.0  # readings below this are noise; push 0.0 to evict stale values

ADS_CONV_REG = 0x00
ADS_CONF_REG = 0x01

_MUX    = {0: 0x4, 1: 0x5, 2: 0x6, 3: 0x7}
_PGA    = 0x1   # ±4.096 V
_DR     = 0x4   # 128 SPS
_LSB_V  = 4.096 / 32768


def _build_config(channel: int) -> int:
    return (
        (1 << 15)
        | (_MUX[channel] << 12)
        | (_PGA << 9)
        | (1 << 8)      # single-shot mode
        | (_DR << 5)
        | 0x0003        # disable comparator
    )


@dataclass
class ADS1115State:
    last_update: float = 0.0
    ch0: float = 0.0
    ch1: float = 0.0
    ch2: float = 0.0
    ch3: float = 0.0
    ch0_raw: float = 0.0
    ch1_raw: float = 0.0
    ch2_raw: float = 0.0
    ch3_raw: float = 0.0


class ADS1115Reader:
    def __init__(self, bus: int = 1, address: int = 0x48, debug: bool = False):
        self.bus     = bus
        self.address = address
        self.debug   = debug
        self._t: Optional[threading.Thread] = None
        self._stop   = threading.Event()
        self._lock   = threading.Lock()
        self._s      = ADS1115State()
        self._hw     = None
        self._dbg_next = 0.0
        self._ma: list[deque] = [deque(maxlen=_MA_WINDOW) for _ in range(4)]

    def start(self) -> None:
        self._t = threading.Thread(target=self._run, daemon=True)
        self._t.start()

    def stop(self) -> None:
        self._stop.set()
        if self._t:
            self._t.join(timeout=1.0)

    def snapshot(self) -> ADS1115State:
        with self._lock:
            return ADS1115State(**self._s.__dict__)

    def _open_bus(self):
        try:
            from smbus2 import SMBus
            return SMBus(self.bus)
        except Exception as e:
            if self.debug:
                print(f"ADS1115 SMBus open failed: {e}")
            return None

    def _read_channel(self, hw, ch: int) -> float:
        conf = _build_config(ch)
        hw.write_i2c_block_data(self.address, ADS_CONF_REG, [(conf >> 8) & 0xFF, conf & 0xFF])
        time.sleep(0.012)  # 128 SPS → ~7.8 ms per conversion
        data = hw.read_i2c_block_data(self.address, ADS_CONV_REG, 2)
        raw = (data[0] << 8) | data[1]
        if raw >= 0x8000:
            raw -= 0x10000
        return max(0.0, raw * _LSB_V)

    def _run(self) -> None:
        while not self._stop.is_set():
            if self._hw is None:
                self._hw = self._open_bus()
                if self._hw is None:
                    time.sleep(1.0)
                    continue

            try:
                raw = [self._read_channel(self._hw, ch) for ch in range(4)]
                for ch, v in enumerate(raw):
                    if v >= _MIN_V:
                        self._ma[ch].append(v)
                averaged = [
                    sum(buf) / len(buf) if buf else 0.0
                    for buf in self._ma
                ]
                now = time.monotonic()
                with self._lock:
                    self._s.last_update = now
                    self._s.ch0, self._s.ch1, self._s.ch2, self._s.ch3 = averaged
                    self._s.ch0_raw, self._s.ch1_raw, self._s.ch2_raw, self._s.ch3_raw = raw

                if self.debug and now >= self._dbg_next:
                    self._dbg_next = now + 1.0
                    print(f"DBG ads1115 raw={[f'{v:.3f}V' for v in raw]} "
                          f"avg={[f'{v:.3f}V' for v in averaged]}")
            except Exception as e:
                if self.debug:
                    now = time.monotonic()
                    if now >= self._dbg_next:
                        self._dbg_next = now + 1.0
                        print(f"DBG ads1115 read error: {e}")
                try:
                    if self._hw:
                        self._hw.close()
                except Exception:
                    pass
                self._hw = None
                time.sleep(0.2)
