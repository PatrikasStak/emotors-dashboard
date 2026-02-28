from __future__ import annotations
import time
from state.dashboard_state import DashboardState

CAN_BUS_STALE_SEC = 1.5
GPS_STALE_SEC = 2.0

POWER_DEADBAND_A = 0.8
RPM_DEADBAND = 30.0

BAT_V_MIN = 36.0
BAT_V_MAX = 50.0

class CombinedReader:
    def __init__(self, can_reader, gps_reader):
        self.can = can_reader
        self.gps = gps_reader

    def snapshot(self) -> DashboardState:
        now = time.monotonic()
        s = DashboardState()

        cs = None
        can_ok = False
        if self.can is not None:
            cs = self.can.snapshot()
            can_ok = (cs.bus_last_update != 0.0 and (now - cs.bus_last_update) < CAN_BUS_STALE_SEC)

        if can_ok and cs is not None:
            s.rpm = float(cs.rpm)
            s.battery_voltage_v = float(cs.battery_voltage_v)
            # CANState now uses motor_current_a and throttle_v
            s.dc_current_a = float(getattr(cs, "dc_current_a", getattr(cs, "motor_current_a", 0.0)))
            s.switch_value_v = float(getattr(cs, "switch_value_v", getattr(cs, "throttle_v", 0.0)))

            if abs(s.dc_current_a) < POWER_DEADBAND_A:
                s.dc_current_a = 0.0
            if s.rpm < RPM_DEADBAND:
                s.rpm = 0.0

            s.power_kw = (s.battery_voltage_v * s.dc_current_a) / 1000.0
            if abs(s.power_kw) < 0.05:
                s.power_kw = 0.0

            s.switch_state = "blue" if 1.0 <= s.switch_value_v <= 4.0 else "red"

            pct = (s.battery_voltage_v - BAT_V_MIN) / (BAT_V_MAX - BAT_V_MIN) * 100.0
            s.battery_pct = max(0.0, min(100.0, pct))

            s.battery_state = "on" if s.battery_voltage_v > 5.0 else "off"
            s.engine_state = "blue"
            s.chip_state = "blue"
            s.ac_current_a = 0.0
        else:
            s.rpm = s.dc_current_a = s.ac_current_a = s.battery_voltage_v = s.power_kw = s.battery_pct = 0.0
            s.switch_value_v = 0.0
            s.switch_state = "off"
            s.battery_state = "off"
            s.engine_state = "off"
            s.chip_state = "off"

        s.speed_kph = 0.0
        s.satellite_state = "off"
        gps_ok = False
        if self.gps is not None:
            gs = self.gps.snapshot()
            gps_ok = (gs.last_update != 0.0 and (now - gs.last_update) < GPS_STALE_SEC)

        s.errors_text = " ".join(filter(None, [
            "No CAN Data" if not can_ok else "",
            "No GPS Data" if not gps_ok else "",
        ]))
        return s
