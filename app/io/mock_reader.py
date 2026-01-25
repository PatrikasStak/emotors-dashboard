# app/io/mock_reader.py
import time
import math
from state.dashboard_state import DashboardState

class MockReader:
    def snapshot(self) -> DashboardState:
        t = time.time()
        phase = (math.sin(t) + 1) / 2

        s = DashboardState()
        s.power_kw = phase * 15
        s.rpm = phase * 6500
        s.speed_kph = phase * 120
        s.battery_pct = 80 - phase * 10

        s.dc_current_a = phase * 120
        s.ac_current_a = phase * 80
        s.battery_voltage_v = 52.0

        s.engine_temp_c = 40 + phase * 60
        s.controller_temp_c = 35 + phase * 50

        s.battery_state = "on"
        s.satellite_state = "on"
        s.engine_state = "blue"
        s.chip_state = "blue"

        return s
