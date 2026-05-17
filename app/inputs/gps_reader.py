from __future__ import annotations

import io
import os
import threading
import time
import termios
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional


def _nmea_checksum_ok(line: str) -> bool:
    if "*" not in line:
        return True
    try:
        body, csum = line.split("*", 1)
    except ValueError:
        return False
    if not body.startswith("$"):
        return False
    calc = 0
    for ch in body[1:]:
        calc ^= ord(ch)
    try:
        return int(csum.strip(), 16) == calc
    except ValueError:
        return False


def _parse_latlon(value: str, hemi: str, is_lat: bool) -> Optional[float]:
    if not value or not hemi:
        return None
    try:
        if is_lat:
            deg = int(value[0:2])
            minutes = float(value[2:])
        else:
            deg = int(value[0:3])
            minutes = float(value[3:])
        coord = deg + minutes / 60.0
        if hemi in ("S", "W"):
            coord = -coord
        return coord
    except Exception:
        return None


def _configure_serial(fd: int, baud: int = 115200) -> None:
    attrs = termios.tcgetattr(fd)

    # input flags
    attrs[0] = termios.IGNPAR
    # output flags
    attrs[1] = 0
    # control flags: 8N1, enable receiver, local mode
    attrs[2] = termios.CREAD | termios.CLOCAL | termios.CS8
    # local flags: raw input
    attrs[3] = 0

    # VMIN/VTIME for 1s read timeout
    attrs[6][termios.VMIN] = 0
    attrs[6][termios.VTIME] = 10

    termios.cfsetispeed(attrs, baud)
    termios.cfsetospeed(attrs, baud)
    termios.tcsetattr(fd, termios.TCSANOW, attrs)


@dataclass
class GPSState:
    gps_last_update: float = 0.0
    fix_valid: bool = False
    speed_kph: float = 0.0
    latitude: float = 0.0
    longitude: float = 0.0
    satellites: int = 0
    raw_sentence: str = ""
    gps_utc: Optional[datetime] = None


class GPSReader:
    def __init__(self, device: str = "/dev/ttyUSB0", baud: int = 115200, debug: bool = False):
        self.device = device
        self.baud = baud
        self.debug = debug
        self._t: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._s = GPSState()
        self._dbg_next = 0.0

    def start(self) -> None:
        self._t = threading.Thread(target=self._run, daemon=True)
        self._t.start()

    def stop(self) -> None:
        self._stop.set()
        if self._t:
            self._t.join(timeout=1.0)

    def snapshot(self) -> GPSState:
        with self._lock:
            return GPSState(**self._s.__dict__)

    def _open_serial(self):
        try:
            import serial
            ser = serial.Serial(self.device, self.baud, timeout=1)
            return ser
        except Exception as e:
            print(f"GPS serial open failed: {e}")
            return None

    def _update_fix(self, fix_valid: bool) -> None:
        with self._lock:
            self._s.fix_valid = fix_valid
            if not fix_valid:
                self._s.speed_kph = 0.0

    def _update_position(self, lat: Optional[float], lon: Optional[float]) -> None:
        if lat is None or lon is None:
            return
        with self._lock:
            self._s.latitude = lat
            self._s.longitude = lon

    def _update_speed(self, speed_kph: float) -> None:
        with self._lock:
            self._s.speed_kph = speed_kph

    def _update_satellites(self, sats: Optional[int]) -> None:
        if sats is None:
            return
        with self._lock:
            self._s.satellites = sats

    def _touch(self, raw: str) -> None:
        now = time.monotonic()
        with self._lock:
            self._s.gps_last_update = now
            self._s.raw_sentence = raw

    def _parse_rmc(self, fields: list[str]) -> None:
        # RMC: time, status, lat, N/S, lon, E/W, speed(knots), course, date
        if len(fields) < 8:
            return
        status = fields[2].strip() if len(fields) > 2 else ""
        fix_valid = status == "A"
        self._update_fix(fix_valid)

        try:
            t_str = fields[1].strip()
            d_str = fields[9].strip() if len(fields) > 9 else ""
            if t_str and d_str and len(t_str) >= 6 and len(d_str) == 6:
                utc_dt = datetime(
                    2000 + int(d_str[4:6]), int(d_str[2:4]), int(d_str[0:2]),
                    int(t_str[0:2]), int(t_str[2:4]), int(t_str[4:6]),
                    tzinfo=timezone.utc,
                )
                with self._lock:
                    self._s.gps_utc = utc_dt
        except Exception:
            pass

        if not fix_valid:
            return

        lat = _parse_latlon(fields[3].strip(), fields[4].strip(), True)
        lon = _parse_latlon(fields[5].strip(), fields[6].strip(), False)
        self._update_position(lat, lon)

        try:
            speed_knots = float(fields[7]) if fields[7] else 0.0
        except ValueError:
            speed_knots = 0.0
        self._update_speed(speed_knots * 1.852)

    def _parse_gga(self, fields: list[str]) -> None:
        # GGA: time, lat, N/S, lon, E/W, fix quality, satellites
        if len(fields) < 8:
            return
        fix_quality = fields[6].strip() if len(fields) > 6 else ""
        try:
            fix_ok = int(fix_quality) > 0
        except ValueError:
            fix_ok = False
        self._update_fix(fix_ok)

        if fix_ok:
            lat = _parse_latlon(fields[2].strip(), fields[3].strip(), True)
            lon = _parse_latlon(fields[4].strip(), fields[5].strip(), False)
            self._update_position(lat, lon)

        sats = None
        try:
            sats = int(fields[7]) if fields[7] else None
        except ValueError:
            sats = None
        self._update_satellites(sats)

    def _parse_gll(self, fields: list[str]) -> None:
        # GLL: lat, N/S, lon, E/W, time, status
        if len(fields) < 7:
            return
        status = fields[6].strip() if len(fields) > 6 else ""
        fix_valid = status == "A"
        self._update_fix(fix_valid)
        if not fix_valid:
            return
        lat = _parse_latlon(fields[1].strip(), fields[2].strip(), True)
        lon = _parse_latlon(fields[3].strip(), fields[4].strip(), False)
        self._update_position(lat, lon)

    def _handle_line(self, line: str) -> None:
        line = line.strip()
        if not line.startswith("$"):
            return
        if line.startswith("$PAIR"):
            return
        if not _nmea_checksum_ok(line):
            return

        self._touch(line)

        body = line[1:]
        if "*" in body:
            body = body.split("*", 1)[0]
        fields = body.split(",")
        if not fields:
            return

        msg_type = fields[0].upper()
        if msg_type.endswith("RMC"):
            self._parse_rmc(fields)
        elif msg_type.endswith("GGA"):
            self._parse_gga(fields)
        elif msg_type.endswith("GLL"):
            self._parse_gll(fields)
        else:
            # ignore other sentence types (e.g. GSV/GSA/VTG/PAIR)
            return

    def _run(self) -> None:
        while not self._stop.is_set():
            buf = self._open_serial()
            if buf is None:
                time.sleep(1.0)
                continue
            try:
                while not self._stop.is_set():
                    try:
                        raw = buf.readline()
                    except Exception:
                        break
                    if not raw:
                        continue
                    line = raw.decode("ascii", errors="ignore")
                    self._handle_line(line)

                    now = time.monotonic()
                    if self.debug and now >= self._dbg_next:
                        self._dbg_next = now + 1.0
                        s = self.snapshot()
                        print(f"DBG gps fix={s.fix_valid} spd={s.speed_kph:.1f}kph sats={s.satellites}")
            finally:
                try:
                    buf.close()
                except Exception:
                    pass
                time.sleep(0.5)
