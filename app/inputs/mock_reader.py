# app/io/mock_reader.py
import time
import math
from state.dashboard_state import DashboardState

MOTOR_TEMP_ALERT_C = 80.0
CONTROLLER_TEMP_ALERT_C = 70.0

class MockReader:
    gps = None

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
        s.engine_state = "red" if s.engine_temp_c > MOTOR_TEMP_ALERT_C else normal_temp_state
        s.chip_state = "red" if s.controller_temp_c > CONTROLLER_TEMP_ALERT_C else normal_temp_state
        s.switch_value_v = 5 + phase * 7
        s.switch_state = "blue" if s.switch_value_v > 1.0 else "off"

        s.borto_pct     = (math.sin(t * 0.4) + 1) / 2 * 100
        s.borto_raw_v   = 2.5
        s.thruster_pct  = (math.sin(t * 0.4 + math.pi) + 1) / 2 * 100
        s.thruster_raw_v = 2.5
        s.adc_ch0_v = 2.5
        s.adc_ch1_v = 0.02
        s.adc_ch2_v = 2.5
        s.adc_ch3_v = 0.03

        return s
