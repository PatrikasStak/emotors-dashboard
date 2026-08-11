# app/state/dashboard_state.py
from dataclasses import dataclass, field
from typing import Optional

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
    reverse_active: bool = False
    neutral_active: bool = False

    engine_state: str = "off"
    chip_state: str = "off"
    switch_state: str = "off"

    switch_value_v: float = 0.0
    errors: list = field(default_factory=list)
    latitude: float = 0.0
    longitude: float = 0.0
    gps_utc: Optional[object] = None
    borto_pct: float = 0.0
    borto_raw_v: float = 0.0
    borto_voltage_v: float = 0.0
    thruster_pct: float = 0.0
    thruster_raw_v: float = 0.0
    thruster_voltage_v: float = 0.0
    adc_ch0_v: float = 0.0
    adc_ch1_v: float = 0.0
    adc_ch2_v: float = 0.0
    adc_ch3_v: float = 0.0
    adc_ch0_raw_v: float = 0.0
    adc_ch1_raw_v: float = 0.0
    adc_ch2_raw_v: float = 0.0
    adc_ch3_raw_v: float = 0.0

    range_km: Optional[float] = None
    range_soc_pct: Optional[float] = None
