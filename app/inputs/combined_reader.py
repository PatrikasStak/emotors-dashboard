from __future__ import annotations
from collections import deque
import time
from state.dashboard_state import DashboardState
from state.range_estimator import RangeEstimator, CELL_OCV_SOC
from config import GPS_MIN_SATELLITES, PACK_CAPACITY_AH, PACK_SERIES_CELLS, INVERT_GEAR_DIRECTION, BATTERY_VOLTAGE_OFFSET_V

CAN_BUS_STALE_SEC = 1.5
GPS_STALE_SEC = 2.0
INA_STALE_SEC = 1.0
ADS_STALE_SEC = 1.0

ADC_MULTIPLIER      = 5.0
BORTO_MIN_RAW_V     = 10.5 / ADC_MULTIPLIER  # 2.1 V — floor of _BORTO_SOC table
THRUSTER_MIN_RAW_V  = 12.0 / ADC_MULTIPLIER  # ~2.000 V — floor of _THRUSTER_SOC table

# Standard 12V flooded lead-acid resting-voltage SOC curve.
_BORTO_SOC = [
    (10.5,   0.0), (11.31, 10.0), (11.58, 20.0), (11.75, 30.0),
    (11.9,  40.0), (12.06, 50.0), (12.2,  60.0), (12.32, 70.0),
    (12.4,  80.0), (12.5,  90.0), (12.7, 100.0),
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

_KLS_ERRORS = {
    0:  "ID Error",
    1:  "Over Volt",
    2:  "Low Volt",
    4:  "Stall",
    5:  "Int Volts",
    6:  "Ctrl Temp",
    7:  "Throttle Err",
    9:  "Int Reset",
    10: "Hall Throttle",
    11: "Angle Sensor",
    14: "Motor Temp",
    15: "Hall Sensor",
}

POWER_DEADBAND_A = 0.8
RPM_DEADBAND = 30.0

RPM_MA_WINDOW    = 15
RPM_SPIKE_FACTOR = 3.0      # reject sample if > factor × running average
RPM_MAX_VALID    = 9500.0   # absolute ceiling — above this is always noise
RPM_SPIKE_REJECT_MAX = 5    # consecutive rejections before trusting the new value instead

BAT_V_VALID_MIN  = 40.0     # anything outside this range from CAN is noise
BAT_V_VALID_MAX  = 80.0
BAT_V_MA_WINDOW  = 8

SPEED_MA_WINDOW  = 3

ERROR_DEBOUNCE_FRAMES   = 4  # frames a KLS error bit must be set/clear to show/hide
REVERSE_DEBOUNCE_FRAMES = 5  # frames reverse_active must be stable before switching

BATTERY_AVG_WINDOW_SEC = 8.0
CURRENT_AVG_WINDOW_SEC = 3.0          # window while RPM is actively changing
CURRENT_AVG_WINDOW_SEC_STEADY = 8.0   # wider window once RPM has held steady, for a cleaner readout
STEADY_RPM_BAND = 300.0               # max RPM swing over the lookback to count as "steady"
STEADY_LOOKBACK_SEC = 2.5             # how far back to check RPM stability
BATTERY_IDLE_THROTTLE_MAX_V = 1.0
BATTERY_IDLE_CONFIRM_SEC = 1.5  # throttle must be idle this long before a voltage sample is trusted as "resting"
BATTERY_PCT_MAX_FALL_PER_SEC = 0.5  # displayed SOC can rise instantly but only fall this fast
MOTOR_TEMP_ALERT_C = 80.0
CONTROLLER_TEMP_ALERT_C = 70.0
GPS_ERROR_DELAY_SEC = 4.0

class CombinedReader:
    def __init__(self, can_reader, gps_reader, ina_reader=None, adc_reader=None):
        self.can = can_reader
        self.gps = gps_reader
        self.ina = ina_reader
        self._gps_lost_at: float = 0.0
        self._last_speed_kph: float = 0.0
        self.adc = adc_reader
        self._borto_idle_since: float = 0.0
        self._thruster_idle_since: float = 0.0
        self._displayed_battery_pct: float = 0.0
        self._last_battery_pct_tick: float = 0.0
        self._dc_samples: deque = deque()
        self._ac_samples: deque = deque()
        self._rpm_history: deque = deque()
        self._current_window_steady: bool = False
        self._borto_voltage_samples = deque()
        self._stable_borto_raw_v = 0.0
        self._thruster_voltage_samples = deque()
        self._stable_thruster_raw_v = 0.0

        self._rpm_window: deque = deque(maxlen=RPM_MA_WINDOW)
        self._rpm_avg: float = 0.0
        self._rpm_reject_count: int = 0

        self._bat_v_window: deque = deque(maxlen=BAT_V_MA_WINDOW)
        self._bat_v_smoothed: float = 0.0

        self._speed_window: deque = deque(maxlen=SPEED_MA_WINDOW)

        self._error_seen: dict = {}
        self._error_gone: dict = {}
        self._stable_error_bits: set = set()

        self._reverse_count: int = 0
        self._reverse_stable: bool = False

        self._neutral_count: int = 0
        self._neutral_stable: bool = False

        self._range = RangeEstimator(PACK_CAPACITY_AH, PACK_SERIES_CELLS)

    def _update_stable_voltage(self, samples: deque, current_stable: float, idle_since: float,
                                now: float, raw_v: float, throttle_v: float) -> tuple[float, float]:
        cutoff = now - BATTERY_AVG_WINDOW_SEC
        while samples and samples[0][0] < cutoff:
            samples.popleft()

        if raw_v <= 0.0:
            return current_stable, idle_since

        if throttle_v < BATTERY_IDLE_THROTTLE_MAX_V:
            if idle_since == 0.0:
                idle_since = now
            # Wait for throttle to be confirmed idle before trusting a sample as
            # "resting" - right at release, voltage may still be sagged from load
            # and would otherwise poison the average with a falsely-low reading.
            if now - idle_since >= BATTERY_IDLE_CONFIRM_SEC:
                samples.append((now, raw_v))
        else:
            idle_since = 0.0

        if samples:
            return sum(v for _, v in samples) / len(samples), idle_since
        elif current_stable == 0.0:
            return raw_v, idle_since
        return current_stable, idle_since

    def snapshot(self) -> DashboardState:
        now = time.monotonic()
        s = DashboardState()

        cs = None
        can_ok = False
        if self.can is not None:
            cs = self.can.snapshot()
            can_ok = (cs.bus_last_update != 0.0 and (now - cs.bus_last_update) < CAN_BUS_STALE_SEC)

        if can_ok and cs is not None:
            # --- RPM: spike rejection + moving average ---
            raw_rpm = float(cs.rpm)
            if raw_rpm < RPM_DEADBAND:
                raw_rpm = 0.0
            if raw_rpm <= RPM_MAX_VALID and (
                self._rpm_avg == 0.0 or raw_rpm <= self._rpm_avg * RPM_SPIKE_FACTOR
            ):
                self._rpm_window.append(raw_rpm)
                self._rpm_avg = sum(self._rpm_window) / len(self._rpm_window)
                self._rpm_reject_count = 0
            elif raw_rpm <= RPM_MAX_VALID:
                # Sustained rejection means this is a real new value, not a noise spike.
                self._rpm_reject_count += 1
                if self._rpm_reject_count >= RPM_SPIKE_REJECT_MAX:
                    self._rpm_window.clear()
                    self._rpm_window.append(raw_rpm)
                    self._rpm_avg = raw_rpm
                    self._rpm_reject_count = 0
            s.rpm = self._rpm_avg

            # --- Steady-state detection (widens the current average window below) ---
            self._rpm_history.append((now, self._rpm_avg))
            rpm_cutoff = now - STEADY_LOOKBACK_SEC
            while self._rpm_history and self._rpm_history[0][0] < rpm_cutoff:
                self._rpm_history.popleft()
            has_full_lookback = bool(self._rpm_history) and (now - self._rpm_history[0][0]) >= STEADY_LOOKBACK_SEC * 0.9
            if has_full_lookback:
                rpm_values = [v for _, v in self._rpm_history]
                self._current_window_steady = (max(rpm_values) - min(rpm_values)) <= STEADY_RPM_BAND
            else:
                self._current_window_steady = False

            # --- Battery voltage: range-gate + moving average ---
            raw_bv = float(cs.battery_voltage_v) + BATTERY_VOLTAGE_OFFSET_V
            if BAT_V_VALID_MIN <= raw_bv <= BAT_V_VALID_MAX:
                self._bat_v_window.append(raw_bv)
                self._bat_v_smoothed = sum(self._bat_v_window) / len(self._bat_v_window)
            s.battery_voltage_v = self._bat_v_smoothed if self._bat_v_smoothed > 0.0 else 0.0

            # CANState now uses motor_current_a and throttle_v
            s.dc_current_a = float(getattr(cs, "dc_current_a", getattr(cs, "motor_current_a", 0.0)))
            s.switch_value_v = float(getattr(cs, "switch_value_v", getattr(cs, "throttle_v", 0.0)))

            s.switch_state = "blue" if 1.0 <= s.switch_value_v <= 4.0 else "red"

            # temps (if provided by CANReader)
            s.controller_temp_c = float(getattr(cs, "controller_temp_c", 0.0))
            s.engine_temp_c = float(getattr(cs, "motor_temp_c", 0.0))
            s.brakes_state = "on" if getattr(cs, "brake_on", False) else "off"

            # --- reverse_active debounce ---
            cmd_state = getattr(cs, "command_state", 1)
            if INVERT_GEAR_DIRECTION and cmd_state in (1, 2):
                # This boat's motor spins the opposite way, so the controller's
                # forward/reverse command bits map to the opposite physical
                # direction. Swap them; leave neutral (0) untouched.
                cmd_state = 1 if cmd_state == 2 else 2
            raw_reverse = (cmd_state == 2)
            if raw_reverse != self._reverse_stable:
                self._reverse_count += 1
                if self._reverse_count >= REVERSE_DEBOUNCE_FRAMES:
                    self._reverse_stable = raw_reverse
                    self._reverse_count = 0
            else:
                self._reverse_count = 0
            s.reverse_active = self._reverse_stable

            # --- neutral_active debounce ---
            raw_neutral = (getattr(cs, "command_state", 1) == 0)
            if raw_neutral != self._neutral_stable:
                self._neutral_count += 1
                if self._neutral_count >= REVERSE_DEBOUNCE_FRAMES:
                    self._neutral_stable = raw_neutral
                    self._neutral_count = 0
            else:
                self._neutral_count = 0
            s.neutral_active = self._neutral_stable

            normal_temp_state = "off"
            s.engine_state = "red" if s.engine_temp_c > MOTOR_TEMP_ALERT_C else normal_temp_state
            s.chip_state = "red" if s.controller_temp_c > CONTROLLER_TEMP_ALERT_C else normal_temp_state
            # show motor current on AC readout
            s.ac_current_a = float(getattr(cs, "motor_current_a", 0.0))
        else:
            s.switch_value_v = 0.0
            s.switch_state = "off"
            s.engine_state = "off"
            s.chip_state = "off"
            self._rpm_history.clear()
            self._current_window_steady = False

        ina_ok = False
        ins = None
        if self.ina is not None:
            ins = self.ina.snapshot()
            ina_ok = (ins.last_update != 0.0 and (now - ins.last_update) < INA_STALE_SEC)

        if ina_ok and ins is not None:
            s.dc_current_a = float(ins.current_a)
            if not can_ok or s.battery_voltage_v == 0.0:
                s.battery_voltage_v = float(ins.voltage_v)

        if abs(s.dc_current_a) < POWER_DEADBAND_A:
            s.dc_current_a = 0.0

        current_window_sec = CURRENT_AVG_WINDOW_SEC_STEADY if self._current_window_steady else CURRENT_AVG_WINDOW_SEC
        cutoff = now - current_window_sec
        self._dc_samples.append((now, s.dc_current_a))
        self._ac_samples.append((now, s.ac_current_a))
        while self._dc_samples and self._dc_samples[0][0] < cutoff:
            self._dc_samples.popleft()
        while self._ac_samples and self._ac_samples[0][0] < cutoff:
            self._ac_samples.popleft()
        s.dc_current_a = sum(v for _, v in self._dc_samples) / len(self._dc_samples)
        s.ac_current_a = sum(v for _, v in self._ac_samples) / len(self._ac_samples)

        if s.battery_voltage_v != 0.0:
            measured_battery_voltage_v = s.battery_voltage_v
            s.power_kw = (measured_battery_voltage_v * s.dc_current_a) / 1000.0
            if abs(s.power_kw) < 0.05:
                s.power_kw = 0.0

            cell_v = measured_battery_voltage_v / PACK_SERIES_CELLS
            pct = _voltage_to_soc(cell_v, CELL_OCV_SOC)
            raw_pct = max(0.0, min(100.0, pct))

            if self._last_battery_pct_tick == 0.0 or raw_pct >= self._displayed_battery_pct:
                self._displayed_battery_pct = raw_pct
            else:
                pct_dt = now - self._last_battery_pct_tick
                max_drop = BATTERY_PCT_MAX_FALL_PER_SEC * pct_dt
                self._displayed_battery_pct = max(raw_pct, self._displayed_battery_pct - max_drop)
            self._last_battery_pct_tick = now

            s.battery_pct = self._displayed_battery_pct
            s.battery_state = "on" if s.battery_pct < 25.0 else "off"
        else:
            s.battery_state = "off"

        s.speed_kph = self._last_speed_kph
        s.satellite_state = "off"
        gps_ok = False
        if self.gps is not None:
            gs = self.gps.snapshot()
            gps_ok = (gs.gps_last_update != 0.0 and (now - gs.gps_last_update) < GPS_STALE_SEC)
            if gps_ok and gs.fix_valid:
                s.satellite_state = "on" if gs.satellites > 0 else "off"
                s.latitude = gs.latitude
                s.longitude = gs.longitude
                s.gps_utc = gs.gps_utc
                raw_speed = float(gs.speed_kph)
                if gs.satellites >= GPS_MIN_SATELLITES:
                    self._speed_window.append(raw_speed)
                    s.speed_kph = sum(self._speed_window) / len(self._speed_window)
                    self._last_speed_kph = s.speed_kph
                    self._gps_lost_at = 0.0
            else:
                if self._gps_lost_at == 0.0:
                    self._gps_lost_at = now

        if self.adc is not None:
            ads = self.adc.snapshot()
            ads_ok = (ads.last_update != 0.0 and (now - ads.last_update) < ADS_STALE_SEC)
            if ads_ok:
                s.borto_raw_v    = ads.ch0_raw
                s.thruster_raw_v = ads.ch3_raw
                s.adc_ch0_v = ads.ch0
                s.adc_ch1_v = ads.ch1
                s.adc_ch2_v = ads.ch2
                s.adc_ch3_v = ads.ch3
                s.adc_ch0_raw_v = ads.ch0_raw
                s.adc_ch1_raw_v = ads.ch1_raw
                s.adc_ch2_raw_v = ads.ch2_raw
                s.adc_ch3_raw_v = ads.ch3_raw
                if ads.ch0 >= BORTO_MIN_RAW_V:
                    self._stable_borto_raw_v, self._borto_idle_since = self._update_stable_voltage(
                        self._borto_voltage_samples, self._stable_borto_raw_v, self._borto_idle_since,
                        now, ads.ch0, s.switch_value_v,
                    )
                if self._stable_borto_raw_v > 0.0:
                    s.borto_voltage_v = self._stable_borto_raw_v * ADC_MULTIPLIER
                    s.borto_pct = _voltage_to_soc(s.borto_voltage_v, _BORTO_SOC)

                if ads.ch3 >= THRUSTER_MIN_RAW_V:
                    self._stable_thruster_raw_v, self._thruster_idle_since = self._update_stable_voltage(
                        self._thruster_voltage_samples, self._stable_thruster_raw_v, self._thruster_idle_since,
                        now, ads.ch3, s.switch_value_v,
                    )
                if self._stable_thruster_raw_v > 0.0:
                    s.thruster_voltage_v = self._stable_thruster_raw_v * ADC_MULTIPLIER
                    s.thruster_pct = _voltage_to_soc(s.thruster_voltage_v, _THRUSTER_SOC)

        errors = []
        if not can_ok:
            errors.append("No CAN")
        gps_gone = (now - self._gps_lost_at) if self._gps_lost_at > 0.0 else 0.0
        if not gps_ok and gps_gone >= GPS_ERROR_DELAY_SEC:
            errors.append("No GPS")
        if self.ina is not None and not ina_ok:
            errors.append("No INA")

        # --- KLS error debounce ---
        if can_ok and cs is not None:
            code = cs.error_code
            for bit in _KLS_ERRORS:
                if code & (1 << bit):
                    self._error_seen[bit] = self._error_seen.get(bit, 0) + 1
                    self._error_gone[bit] = 0
                    if self._error_seen[bit] >= ERROR_DEBOUNCE_FRAMES:
                        self._stable_error_bits.add(bit)
                else:
                    self._error_gone[bit] = self._error_gone.get(bit, 0) + 1
                    self._error_seen[bit] = 0
                    if self._error_gone[bit] >= ERROR_DEBOUNCE_FRAMES:
                        self._stable_error_bits.discard(bit)
            for bit, name in _KLS_ERRORS.items():
                if bit in self._stable_error_bits:
                    errors.append(name)
        else:
            self._stable_error_bits.clear()
            self._error_seen.clear()
            self._error_gone.clear()

        s.errors = errors

        self._range.tick(s.dc_current_a, s.battery_voltage_v, s.speed_kph, neutral=s.neutral_active)
        s.range_km = self._range.range_km
        s.range_hours = self._range.range_hours
        s.range_soc_pct = self._range.soc_pct

        return s
