from __future__ import annotations

import threading
import time
import csv
from dataclasses import dataclass, field
from typing import Optional, Dict, Tuple, Any, Callable

import can


# === Observed standard 11-bit IDs ===
ID_6E4 = 0x6E4
ID_6E5 = 0x6E5

# === Helpers ===
def u16_le(b: bytes, i: int) -> int:
    return (b[i] & 0xFF) | ((b[i + 1] & 0xFF) << 8)

def u16_be(b: bytes, i: int) -> int:
    return ((b[i] & 0xFF) << 8) | (b[i + 1] & 0xFF)

def s16(x: int) -> int:
    return x - 0x10000 if (x & 0x8000) else x

def s16_le(b: bytes, i: int) -> int:
    return s16(u16_le(b, i))

def s16_be(b: bytes, i: int) -> int:
    return s16(u16_be(b, i))

def ema(prev: float, new: float, a: float) -> float:
    return new if prev == 0.0 else (prev * (1.0 - a) + new * a)


# === State ===
@dataclass
class CANState:
    bus_last_update: float = 0.0

    # decoded "final" values (fill once mapping is known)
    rpm: float = 0.0
    battery_voltage_v: float = 0.0
    dc_current_a: float = 0.0
    throttle_v: float = 0.0

    # raw/mux visibility (useful while reverse engineering)
    last_6e4_mux: int = 0
    last_6e5_mux: int = 0
    last_6e4_data: bytes = b"\x00" * 8
    last_6e5_data: bytes = b"\x00" * 8

    # timing
    last_6e4_t: float = 0.0
    last_6e5_t: float = 0.0

    # optional: decoded debug fields (you can repurpose)
    decoded: Dict[str, Any] = field(default_factory=dict)


# === Field spec / decode map (plug-in) ===
@dataclass(frozen=True)
class FieldSpec:
    """Describe one decoded quantity inside a (can_id, mux) page."""
    name: str
    offset: int                 # start byte for u16/s16 (1..6 typically)
    kind: str                   # "u16_le", "u16_be", "s16_le", "s16_be", or "u8"
    scale: float = 1.0          # multiply after extraction
    add: float = 0.0            # add after scaling
    clamp_min: Optional[float] = None
    clamp_max: Optional[float] = None
    smooth_a: Optional[float] = None  # if set, EMA smoothing factor


class CANReader:
    """
    11-bit multiplex reader for Kelly KLS (0x6E4 / 0x6E5 observed).
    - Byte0 = mux/page selector
    - Bytes1..7 carry page payload

    You can run it in "discovery" mode (no decode map),
    then later drop in decode_map with deterministic offsets/scales.
    """

    def __init__(
        self,
        channel: str = "can0",
        debug: bool = False,
        log_csv_path: Optional[str] = None,
        decode_map: Optional[Dict[Tuple[int, int], Tuple[FieldSpec, ...]]] = None,
    ):
        self.channel = channel
        self.debug = debug
        self.log_csv_path = log_csv_path
        self.decode_map = decode_map or {}  # {(can_id, mux): (FieldSpec,...), ...}

        self._bus: Optional[can.Bus] = None
        self._t: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._s = CANState()

        self._dbg_next = 0.0

        # CSV logger
        self._csv_f = None
        self._csv_w = None

    def start(self) -> None:
        # Standard 11-bit filters
        filters = [
            {"can_id": ID_6E4, "can_mask": 0x7FF, "extended": False},
            {"can_id": ID_6E5, "can_mask": 0x7FF, "extended": False},
        ]
        self._bus = can.interface.Bus(channel=self.channel, interface="socketcan", can_filters=filters)

        if self.log_csv_path:
            self._csv_f = open(self.log_csv_path, "w", newline="")
            self._csv_w = csv.writer(self._csv_f)
            self._csv_w.writerow([
                "monotonic_ts", "can_id_hex", "mux_hex",
                "b0","b1","b2","b3","b4","b5","b6","b7",
                "u16le1","u16le3","u16le5","u16be1","u16be3","u16be5",
                "s16le1","s16le3","s16le5","s16be1","s16be3","s16be5",
            ])

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
        if self._csv_f:
            try:
                self._csv_f.close()
            except Exception:
                pass

    def snapshot(self) -> CANState:
        with self._lock:
            # shallow copy is fine; bytes are immutable
            return CANState(**self._s.__dict__)

    # ---------- internal ----------
    def _extract(self, d: bytes, spec: FieldSpec) -> float:
        if spec.kind == "u8":
            raw = d[spec.offset]  # for u8 we use offset as the byte index
            val = float(raw)
        elif spec.kind == "u16_le":
            val = float(u16_le(d, spec.offset))
        elif spec.kind == "u16_be":
            val = float(u16_be(d, spec.offset))
        elif spec.kind == "s16_le":
            val = float(s16_le(d, spec.offset))
        elif spec.kind == "s16_be":
            val = float(s16_be(d, spec.offset))
        else:
            raise ValueError(f"Unknown FieldSpec.kind: {spec.kind}")

        val = val * spec.scale + spec.add

        if spec.clamp_min is not None:
            val = max(spec.clamp_min, val)
        if spec.clamp_max is not None:
            val = min(spec.clamp_max, val)

        return val

    def _apply_decode_map(self, can_id: int, mux: int, d: bytes) -> Dict[str, float]:
        out: Dict[str, float] = {}
        specs = self.decode_map.get((can_id, mux))
        if not specs:
            return out

        with self._lock:
            # for smoothing we need previous values
            prev_decoded = dict(self._s.decoded)

        for spec in specs:
            v = self._extract(d, spec)
            if spec.smooth_a is not None:
                prev = float(prev_decoded.get(spec.name, 0.0))
                v = ema(prev, v, spec.smooth_a)
            out[spec.name] = v

        return out

    def _log_csv(self, now: float, can_id: int, mux: int, d: bytes) -> None:
        if not self._csv_w:
            return

        # common u16 start positions you’ll use a lot in muxed frames
        u16le1 = u16_le(d, 1)
        u16le3 = u16_le(d, 3)
        u16le5 = u16_le(d, 5)
        u16be1 = u16_be(d, 1)
        u16be3 = u16_be(d, 3)
        u16be5 = u16_be(d, 5)

        self._csv_w.writerow([
            f"{now:.6f}", f"0x{can_id:03X}", f"0x{mux:02X}",
            d[0], d[1], d[2], d[3], d[4], d[5], d[6], d[7],
            u16le1, u16le3, u16le5, u16be1, u16be3, u16be5,
            s16(u16le1), s16(u16le3), s16(u16le5),
            s16(u16be1), s16(u16be3), s16(u16be5),
        ])

        # flush lightly so you don’t lose data on power cut
        # (comment out if you want max throughput)
        self._csv_f.flush()

    def _run(self) -> None:
        assert self._bus is not None

        while not self._stop.is_set():
            msg = self._bus.recv(timeout=1.0)
            if msg is None:
                continue

            # only standard frames are expected here
            if msg.is_extended_id:
                continue

            d = bytes(msg.data)
            if len(d) < 8:
                continue

            now = time.monotonic()
            can_id = msg.arbitration_id
            mux = d[0]

            with self._lock:
                self._s.bus_last_update = now

                if can_id == ID_6E4:
                    self._s.last_6e4_mux = mux
                    self._s.last_6e4_data = d
                    self._s.last_6e4_t = now
                elif can_id == ID_6E5:
                    self._s.last_6e5_mux = mux
                    self._s.last_6e5_data = d
                    self._s.last_6e5_t = now

            # Log raw + candidate words for offline correlation
            self._log_csv(now, can_id, mux, d)

            # Apply decode map if known for that page
            decoded = self._apply_decode_map(can_id, mux, d)
            if decoded:
                with self._lock:
                    self._s.decoded.update(decoded)

                    # Optional: wire canonical fields when you define them
                    if "rpm" in decoded:
                        self._s.rpm = float(decoded["rpm"])
                    if "battery_voltage_v" in decoded:
                        self._s.battery_voltage_v = float(decoded["battery_voltage_v"])
                    if "dc_current_a" in decoded:
                        self._s.dc_current_a = float(decoded["dc_current_a"])
                    if "throttle_v" in decoded:
                        self._s.throttle_v = float(decoded["throttle_v"])

            # Debug print: show mux + key candidate words so you can eyeball it live
            if self.debug and now >= self._dbg_next:
                self._dbg_next = now + 0.25  # 4 Hz debug
                u1l, u3l, u5l = u16_le(d, 1), u16_le(d, 3), u16_le(d, 5)
                u1b, u3b, u5b = u16_be(d, 1), u16_be(d, 3), u16_be(d, 5)
                print(
                    f"0x{can_id:03X} mux=0x{mux:02X} "
                    f"LE@1/3/5={u1l}/{u3l}/{u5l} "
                    f"BE@1/3/5={u1b}/{u3b}/{u5b} "
                    f"raw={d.hex(' ')}"
                )