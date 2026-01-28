# app/state/dashboard_state.py
from dataclasses import dataclass

@dataclass
class DashboardState:
    power_kw: float = 0.0
    rpm: float = 0.0
    speed_kph: float = 0.0
    battery_pct: float = 0.0

    dc_current_a: float = 0.0
    ac_current_a: float = 0.0
    battery_voltage_v: float = 0.0

    engine_temp_c: float = 0.0
    controller_temp_c: float = 0.0

    battery_state: str = "off"
    brakes_state: str = "off"
    satellite_state: str = "off"

    engine_state: str = "off"
    chip_state: str = "off"
    switch_state: str = "red"

    switch_value_v: float = 0.0
    errors_text: str = ""
