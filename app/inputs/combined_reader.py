# app/inputs/combined_reader.py
from __future__ import annotations
import time
from state.dashboard_state import DashboardState

class CombinedReader:
    def __init__(self, can_reader, gps_reader):
        self.can = can_reader
        self.gps = gps_reader

    def snapshot(self) -> DashboardState:
        cs = self.can.snapshot()
        gs = self.gps.snapshot()

        s = DashboardState()

        # CAN (Kelly)
        s.rpm = cs.rpm
        s.dc_current_a = cs.motor_current_a
        s.battery_voltage_v = cs.battery_voltage_v
        s.controller_temp_c = cs.controller_temp_c
        s.engine_temp_c = cs.motor_temp_c
        # Optional switch voltage if the CAN payload exposes it.
        s.switch_value_v = getattr(cs, "switch_voltage_v", 0.0)

        # If you want power and don't have kW directly:
        s.power_kw = (s.battery_voltage_v * s.dc_current_a) / 1000.0

        # GPS
        s.speed_kph = gs.speed_kph
        s.satellite_state = "on" if gs.has_fix else "off"

        # Battery % not in Kelly broadcast; leave 0 unless you have BMS later
        # s.battery_pct = ...

        # Basic icon logic (temporary—refine once you confirm bits)
        s.battery_state = "on" if s.battery_voltage_v > 5 else "off"

        # Switch bits: fill once confirmed on Pi
        # For now default off:
        s.brakes_state = "off"
        s.switch_state = "blue" if s.switch_value_v > 1.0 else "off"

        # Error bits: if any error, red else blue
        s.engine_state = "red" if cs.error_bits else "blue"
        s.chip_state = "red" if cs.error_bits else "blue"

        return s
