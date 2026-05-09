from __future__ import annotations
from collections import deque
import time
from state.dashboard_state import DashboardState

CAN_BUS_STALE_SEC = 1.5
GPS_STALE_SEC = 2.0
INA_STALE_SEC = 1.0
ADS_STALE_SEC = 1.0

ADC_MULTIPLIER = 6.0  # resistor divider ratio
ADC_MIN_RAW_V  = 1.0  # below this → sensor not connected

_BORTO_SOC = [
    (11.6,   0.0), (11.8,  20.0), (12.0,  40.0),
    (12.2,  60.0), (12.4,  80.0), (12.5,  90.0), (12.7, 100.0),
]
_THRUSTER_SOC = [
    (12.0,   0.0), (12.8,   5.0), (13.1,  20.0),
    (13.2,  40.0), (13.3,  70.0), (13.4,  90.0), (13.6, 100.0),
]


def _voltage_to_soc(voltage: float, table: list) -> float:
    if voltage <= table[0][0]:
        return table[0][1]
    if voltage >= table[-1][0]:
        return table[-1][1]
    for i in range(len(table) - 1):
        v0, s0 = table[i]
        v1, s1 = table[i + 1]
        if v0 <= voltage <= v1:
            t = (voltage - v0) / (v1 - v0)
            return s0 + t * (s1 - s0)
    return table[-1][1]

POWER_DEADBAND_A = 0.8
RPM_DEADBAND = 30.0

BAT_V_MIN = 48.0
BAT_V_MAX = 58.0
BATTERY_AVG_WINDOW_SEC = 20.0
BATTERY_IDLE_THROTTLE_MAX_V = 1.0
TEMP_ALERT_C = 75.0

class CombinedReader:
    def __init__(self, can_reader, gps_reader, ina_reader=None, adc_reader=None):
        self.can = can_reader
        self.gps = gps_reader
        self.ina = ina_reader
        self.adc = adc_reader
        self._battery_voltage_samples = deque()
        self._stable_battery_voltage_v = 0.0

    def _update_stable_battery_voltage(self, now: float, voltage_v: float, throttle_v: float) -> float:
        cutoff = now - BATTERY_AVG_WINDOW_SEC
        while self._battery_voltage_samples and self._battery_voltage_samples[0][0] < cutoff:
            self._battery_voltage_samples.popleft()

        if voltage_v <= 0.0:
            return self._stable_battery_voltage_v

        if throttle_v < BATTERY_IDLE_THROTTLE_MAX_V:
            self._battery_voltage_samples.append((now, voltage_v))

        if self._battery_voltage_samples:
            total = sum(v for _, v in self._battery_voltage_samples)
            self._stable_battery_voltage_v = total / len(self._battery_voltage_samples)
        elif self._stable_battery_voltage_v == 0.0:
            self._stable_battery_voltage_v = voltage_v

        return self._stable_battery_voltage_v

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

            if s.rpm < RPM_DEADBAND:
                s.rpm = 0.0

            s.switch_state = "blue" if 1.0 <= s.switch_value_v <= 4.0 else "red"

            # temps (if provided by CANReader)
            s.controller_temp_c = float(getattr(cs, "controller_temp_c", 0.0))
            s.engine_temp_c = float(getattr(cs, "motor_temp_c", 0.0))
            s.brakes_state = "on" if getattr(cs, "brake_on", False) else "off"
            s.reverse_active = bool(getattr(cs, "reverse_active", False))

            normal_temp_state = "off"
            s.engine_state = "red" if s.engine_temp_c > TEMP_ALERT_C else normal_temp_state
            s.chip_state = "red" if s.controller_temp_c > TEMP_ALERT_C else normal_temp_state
            # show motor current on AC readout
            s.ac_current_a = float(getattr(cs, "motor_current_a", 0.0))
        else:
            s.switch_value_v = 0.0
            s.switch_state = "off"
            s.engine_state = "off"
            s.chip_state = "off"

        ina_ok = False
        ins = None
        if self.ina is not None:
            ins = self.ina.snapshot()
            ina_ok = (ins.last_update != 0.0 and (now - ins.last_update) < INA_STALE_SEC)

        if ina_ok and ins is not None:
            if not can_ok:
                s.dc_current_a = float(ins.current_a)
            if not can_ok or s.battery_voltage_v == 0.0:
                s.battery_voltage_v = float(ins.voltage_v)

        if abs(s.dc_current_a) < POWER_DEADBAND_A:
            s.dc_current_a = 0.0

        if s.battery_voltage_v != 0.0:
            measured_battery_voltage_v = s.battery_voltage_v
            s.power_kw = (measured_battery_voltage_v * s.dc_current_a) / 1000.0
            if abs(s.power_kw) < 0.05:
                s.power_kw = 0.0

            stable_battery_voltage_v = self._update_stable_battery_voltage(
                now,
                measured_battery_voltage_v,
                s.switch_value_v,
            )
            pct = (stable_battery_voltage_v - BAT_V_MIN) / (BAT_V_MAX - BAT_V_MIN) * 100.0
            s.battery_pct = max(0.0, min(100.0, pct))
            s.battery_state = "on" if s.battery_voltage_v < 50.0 else "off"
        else:
            s.battery_state = "off"

        s.speed_kph = 0.0
        s.satellite_state = "off"
        gps_ok = False
        if self.gps is not None:
            gs = self.gps.snapshot()
            gps_ok = (gs.gps_last_update != 0.0 and (now - gs.gps_last_update) < GPS_STALE_SEC)
            if gps_ok and gs.fix_valid:
                s.speed_kph = float(gs.speed_kph)
                s.satellite_state = "on" if gs.satellites > 0 else "off"

        if self.adc is not None:
            ads = self.adc.snapshot()
            ads_ok = (ads.last_update != 0.0 and (now - ads.last_update) < ADS_STALE_SEC)
            if ads_ok:
                borto_raw    = ads.ch0
                thruster_raw = ads.ch3
                s.borto_raw_v    = borto_raw
                s.thruster_raw_v = thruster_raw
                s.adc_ch0_v = ads.ch0
                s.adc_ch1_v = ads.ch1
                s.adc_ch2_v = ads.ch2
                s.adc_ch3_v = ads.ch3
                if borto_raw > ADC_MIN_RAW_V:
                    s.borto_pct = _voltage_to_soc(borto_raw * ADC_MULTIPLIER, _BORTO_SOC)
                if thruster_raw > ADC_MIN_RAW_V:
                    s.thruster_pct = _voltage_to_soc(thruster_raw * ADC_MULTIPLIER, _THRUSTER_SOC)

        s.errors_text = " ".join(filter(None, [
            "No CAN Data" if not can_ok else "",
            "No GPS Data" if not gps_ok else "",
            "No INA Data" if (self.ina is not None and not ina_ok) else "",
        ]))
        return s
