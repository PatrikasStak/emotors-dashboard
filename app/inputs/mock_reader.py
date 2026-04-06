# app/io/mock_reader.py
import time
import math
from state.dashboard_state import DashboardState

TEMP_ALERT_C = 75.0

class MockReader:
    def snapshot(self) -> DashboardState:
        t = time.time()
        phase = (math.sin(t) + 1) / 2

        s = DashboardState()
        s.power_kw = phase * 15
        s.rpm = phase * 6500
        s.speed_kph = phase * 20
        s.battery_pct = phase * 100

        s.dc_current_a = phase * 120
        s.ac_current_a = phase * 80
        s.battery_voltage_v = 52.0

        s.engine_temp_c = 40 + phase * 60
        s.controller_temp_c = 35 + phase * 50

        s.battery_state = "on"
        s.satellite_state = "on"
        s.reverse_active = False
        normal_temp_state = "off"
        s.engine_state = "red" if s.engine_temp_c > TEMP_ALERT_C else normal_temp_state
        s.chip_state = "red" if s.controller_temp_c > TEMP_ALERT_C else normal_temp_state
        s.switch_value_v = 5 + phase * 7
        s.switch_state = "blue" if s.switch_value_v > 1.0 else "off"

        return s
