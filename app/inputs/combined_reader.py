# app/inputs/combined_reader.py
from __future__ import annotations

import time
from state.dashboard_state import DashboardState

CAN_STALE_SEC = 0.5      # Kelly broadcasts ~50ms, so 0.5s is generous
GPS_STALE_SEC = 2.0

class CombinedReader:
    def __init__(self, can_reader, gps_reader):
        self.can = can_reader    # may be None
        self.gps = gps_reader    # should exist, but may have no device

    def snapshot(self) -> DashboardState:
        now = time.monotonic()
        s = DashboardState()

        # ----------------------------
        # CAN
        # ----------------------------
        cs = None
        can_ok = False
        if self.can is not None:
            try:
                cs = self.can.snapshot()
                can_ok = (getattr(cs, "last_update", 0.0) != 0.0) and ((now - cs.last_update) < CAN_STALE_SEC)
            except Exception:
                # Treat any CAN read issue as CAN unavailable
                cs = None
                can_ok = False

        if can_ok and cs is not None:
            s.rpm = cs.rpm
            s.dc_current_a = cs.motor_current_a
            s.battery_voltage_v = cs.battery_voltage_v
            s.controller_temp_c = cs.controller_temp_c
            s.engine_temp_c = cs.motor_temp_c
            s.power_kw = (s.battery_voltage_v * s.dc_current_a) / 1000.0

            s.engine_state = "red" if cs.error_bits else "blue"
            s.chip_state = "red" if cs.error_bits else "blue"
            s.battery_state = "on" if s.battery_voltage_v > 5 else "off"
        else:
            # Safe defaults when CAN missing/stale
            s.rpm = 0.0
            s.dc_current_a = 0.0
            s.battery_voltage_v = 0.0
            s.power_kw = 0.0
            s.controller_temp_c = 0.0
            s.engine_temp_c = 0.0
            s.engine_state = "off"
            s.chip_state = "off"
            s.battery_state = "off"

        # ----------------------------
        # GPS
        # ----------------------------
        gs = None
        gps_recent = False
        gps_ok = False
        if self.gps is not None:
            try:
                gs = self.gps.snapshot()
                gps_recent = (getattr(gs, "last_update", 0.0) != 0.0) and ((now - gs.last_update) < GPS_STALE_SEC)
                gps_ok = gps_recent and bool(getattr(gs, "has_fix", False))
            except Exception:
                gs = None
                gps_recent = False
                gps_ok = False

        s.speed_kph = (gs.speed_kph if (gs is not None and gps_recent) else 0.0)
        s.satellite_state = "on" if gps_ok else "off"

        # ----------------------------
        # Errors overlay text
        # ----------------------------
        # You want CAN missing => show CAN in errors box
        # GPS missing/fixless => satellite icon off AND show GPS text (optional)
        s.errors_text = " ".join(filter(None, [
            "No CAN Data" if not can_ok else "",
            "No GPS Data" if not gps_ok else "",
        ]))

        return s
