import os
os.system("unclutter -idle 0 >/dev/null 2>&1 &")
import array
import math
import sys
import pygame
from datetime import datetime, timezone
import pygame.gfxdraw
from state.runtime_tracker import RuntimeTracker
from state.gps_logger import GpsLogger
from state.drive_handler import DriveHandler


# ----------------------------
# Config
from config import SPEED_FULL_SCALE_KPH, SPEED_MAX_VALUE, SPEED_UNIT, BAR_MODE, OIL_CHANGE_HOURS, IS_PI, KW_FULL_SCALE_KW
# ----------------------------
DESIGN_W, DESIGN_H = 1920, 1080   # logical design canvas
FPS = 60
BATTERY_ARC_SMOOTH_TAU_SEC = 0.45
GAUGE_ARC_SMOOTH_TAU_SEC = 0.18
SPEED_ARC_SMOOTH_TAU_SEC = 0.7

# For development on your laptop:
#WINDOWED = True
#WINDOW_SIZE = (1024, 600)         # change to (1920, 1080) if you want|1280 720

# For Raspberry Pi deployment later:
WINDOWED = False  # fullscreen


# ----------------------------
# Utilities: scaling + drawing
# ----------------------------
class Scaler:
    """
    Maps DESIGN_W x DESIGN_H coordinates into the actual screen while preserving aspect ratio.
    Adds letterboxing (offset) when aspect ratios differ.
    """
    def __init__(self, screen_w: int, screen_h: int, design_w: int, design_h: int):
        self.screen_w = screen_w
        self.screen_h = screen_h
        self.design_w = design_w
        self.design_h = design_h

        sx = screen_w / design_w
        sy = screen_h / design_h
        self.scale = min(sx, sy)

        out_w = int(design_w * self.scale)
        out_h = int(design_h * self.scale)

        self.off_x = (screen_w - out_w) // 2
        self.off_y = (screen_h - out_h) // 2

    def s(self, v: float) -> int:
        return int(v * self.scale)

    def pt(self, x: float, y: float) -> tuple[int, int]:
        return (self.off_x + int(x * self.scale), self.off_y + int(y * self.scale))


def clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def smooth_toward(current: float | None, target: float, dt: float, tau_sec: float) -> float:
    if current is None:
        return target
    alpha = 1.0 - math.exp(-dt / tau_sec)
    return current + (target - current) * alpha


def draw_solid_arc_ccw(
    surface: pygame.Surface,
    center: tuple[int, int],
    inner_radius: float,
    outer_radius: float,
    start_rad: float,
    stop_rad: float,
    color: pygame.Color,
) -> None:
    """
    Draws a solid arc band by filling a polygon ring segment.
    This avoids tiny gaps that can appear with thick arcs during motion.
    """
    two_pi = math.tau
    start = start_rad % two_pi
    stop = stop_rad % two_pi

    if abs(stop - start) < 1e-9:
        return

    if stop <= start:
        stop += two_pi

    step = 1.0 / max(1.0, outer_radius)
    cx, cy = center
    outer_pts = []
    inner_pts = []

    a = start
    while a <= stop:
        ca, sa = math.cos(a), math.sin(a)
        outer_pts.append((int(cx + outer_radius * ca), int(cy - outer_radius * sa)))
        inner_pts.append((int(cx + inner_radius * ca), int(cy - inner_radius * sa)))
        a += step

    # Ensure we hit the exact end angle.
    ca, sa = math.cos(stop), math.sin(stop)
    outer_pts.append((int(cx + outer_radius * ca), int(cy - outer_radius * sa)))
    inner_pts.append((int(cx + inner_radius * ca), int(cy - inner_radius * sa)))

    # Build polygon for the ring segment.
    pts = outer_pts + inner_pts[::-1]
    pygame.gfxdraw.filled_polygon(surface, pts, color)


def mask_bar_image(image: pygame.Surface, fraction: float) -> pygame.Surface:
    w, h = image.get_size()
    mask = pygame.Surface((w, h), pygame.SRCALPHA)
    fill_h = int(h * clamp(fraction, 0.0, 1.0))
    if fill_h > 0:
        pygame.draw.rect(mask, pygame.Color(255, 255, 255), (0, h - fill_h, w, fill_h))
    masked = image.copy()
    masked.blit(mask, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
    return masked


def mask_arc_image(
    image: pygame.Surface,
    start_rad: float,
    stop_rad: float,
    direction: str,
) -> pygame.Surface:
    mask = pygame.Surface(image.get_size(), pygame.SRCALPHA)
    cx = image.get_width() / 2.0
    cy = image.get_height() / 2.0
    radius = min(image.get_width(), image.get_height()) / 2.0

    if direction.lower() == "cw":
        draw_solid_arc_ccw(mask, (int(cx), int(cy)), 0.0, radius, stop_rad, start_rad, pygame.Color(255, 255, 255))
    else:
        draw_solid_arc_ccw(mask, (int(cx), int(cy)), 0.0, radius, start_rad, stop_rad, pygame.Color(255, 255, 255))

    masked = image.copy()
    masked.blit(mask, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
    return masked


def adjust_color(color: pygame.Color, factor: float) -> pygame.Color:
    return pygame.Color(
        max(0, min(255, int(color.r * factor))),
        max(0, min(255, int(color.g * factor))),
        max(0, min(255, int(color.b * factor))),
        color.a,
    )


def value_to_angle_deg(v: float, vmin: float, vmax: float,
                       start_deg: float, end_deg: float, direction: str) -> float:
    """
    Maps value to an angle in degrees in pygame's angle system:
    - 0° = to the right (3 o'clock)
    - 90° = up (12 o'clock)
    Positive angles are CCW.
    We support gauge sweep direction:
      direction = "cw" or "ccw"
    """
    v = clamp(v, vmin, vmax)
    t = 0.0 if vmax == vmin else (v - vmin) / (vmax - vmin)

    start = start_deg
    end = end_deg

    # We treat start/end as absolute angles (0..360 OK, but can be any)
    # For CW gauges, sweep is going "backwards" from start to end.
    if direction.lower() == "cw":
        raw_sweep = start - end
        sweep = raw_sweep % 360.0
        if sweep == 0.0 and raw_sweep != 0.0:
            sweep = 360.0
        ang = start - t * sweep
    else:
        raw_sweep = end - start
        sweep = raw_sweep % 360.0
        if sweep == 0.0 and raw_sweep != 0.0:
            sweep = 360.0
        ang = start + t * sweep

    return ang


def draw_gauge_bar(screen: pygame.Surface, sc: Scaler,
                   center_design: tuple[float, float],
                   radius_design: float,
                   value: float, vmin: float, vmax: float,
                   start_deg: float, end_deg: float, direction: str,
                   thickness_design: float,
                   color: pygame.Color) -> None:
    cx, cy = sc.pt(center_design[0], center_design[1])
    r = sc.s(radius_design)
    rect = pygame.Rect(cx - r, cy - r, 2 * r, 2 * r)

    start_deg_abs = start_deg
    current_deg = value_to_angle_deg(value, vmin, vmax, start_deg, end_deg, direction)

    start_rad = math.radians(start_deg_abs)
    curr_rad = math.radians(current_deg)

    width = max(1, sc.s(thickness_design))
    half = width / 2.0
    inner = max(1.0, r - half)
    outer = max(inner + 1.0, r + half)
    mid = (inner + outer) / 2.0

    outer_color = adjust_color(color, 0.75)
    inner_color = adjust_color(color, 1.15)
    highlight_color = adjust_color(color, 1.35)

    # CW: bar is CW from start->current == CCW current->start
    if direction.lower() == "cw":
        draw_solid_arc_ccw(screen, (cx, cy), mid, outer, curr_rad, start_rad, outer_color)
        draw_solid_arc_ccw(screen, (cx, cy), inner, mid, curr_rad, start_rad, inner_color)
        draw_solid_arc_ccw(screen, (cx, cy), inner, inner + 1.0, curr_rad, start_rad, highlight_color)
    else:
        draw_solid_arc_ccw(screen, (cx, cy), mid, outer, start_rad, curr_rad, outer_color)
        draw_solid_arc_ccw(screen, (cx, cy), inner, mid, start_rad, curr_rad, inner_color)
        draw_solid_arc_ccw(screen, (cx, cy), inner, inner + 1.0, start_rad, curr_rad, highlight_color)


def screen_px_to_design(sc: Scaler, pos: tuple[int, int]) -> tuple[float, float]:
    return ((pos[0] - sc.off_x) / sc.scale, (pos[1] - sc.off_y) / sc.scale)


def _is_daytime(lat: float, lon: float, utc_dt=None) -> bool:
    now = utc_dt if utc_dt is not None else datetime.now(timezone.utc)
    doy = now.timetuple().tm_yday
    decl = math.radians(23.45 * math.sin(math.radians(360 / 365 * (doy - 81))))
    b = math.radians(360 / 365 * (doy - 81))
    eot_min = 9.87 * math.sin(2 * b) - 7.53 * math.cos(b) - 1.5 * math.sin(b)
    solar_noon = 12.0 - lon / 15.0 - eot_min / 60.0
    utc_h = now.hour + now.minute / 60.0 + now.second / 3600.0
    hour_angle = math.radians(15.0 * (utc_h - solar_noon))
    lat_r = math.radians(lat)
    sin_elev = math.sin(lat_r) * math.sin(decl) + math.cos(lat_r) * math.cos(decl) * math.cos(hour_angle)
    return math.degrees(math.asin(max(-1.0, min(1.0, sin_elev)))) > 0


def _generate_beep(freq=880, duration=0.25, volume=0.5, sample_rate=44100):
    n = int(sample_rate * duration)
    fade = int(sample_rate * 0.01)
    buf = array.array('h')
    for i in range(n):
        t = i / sample_rate
        env = min(i / fade, 1.0, (n - i) / fade)
        val = int(32767 * volume * env * math.sin(2 * math.pi * freq * t))
        buf.append(val)
        buf.append(val)  # stereo
    return pygame.mixer.Sound(buffer=buf)


# ----------------------------
# Main
# ----------------------------
def main(reader):
    pygame.mixer.pre_init(44100, -16, 2, 512)
    pygame.init()
    pygame.display.init()
    pygame.display.set_caption("Dashboard Base")

    info = pygame.display.Info()
    screen = pygame.display.set_mode(
        (info.current_w, info.current_h),
        pygame.FULLSCREEN
    )

    pygame.mouse.set_visible(False)
    pygame.event.set_grab(True)
    pygame.mouse.get_rel()  # flush motion so cursor doesn't reappear
    

    clock = pygame.time.Clock()
    runtime = RuntimeTracker()
    gps_logger = GpsLogger()
    drive_handler = DriveHandler(runtime, gps_logger)

    # ----------------------------
    # Load assets (once) and scale to the current screen using Scaler
    # ----------------------------
    def load_img(path: str, alpha: bool = True) -> pygame.Surface:
        img = pygame.image.load(path)
        img = img.convert_alpha() if alpha else img.convert()
        # Scale to current output size based on sc.scale.
        w = max(1, sc.s(img.get_width()))
        h = max(1, sc.s(img.get_height()))
        return pygame.transform.smoothscale(img, (w, h))

    sc = Scaler(screen.get_width(), screen.get_height(), DESIGN_W, DESIGN_H)

    assets = {
        "bg": load_img("assets/bg.png", alpha=False),
        "rpm": load_img("assets/gauges/rpm.png"),
        "speed": load_img("assets/gauges/speed.png"),
        "kwbg": load_img("assets/gauges/kwbg.png"),
        "kw": load_img("assets/gauges/kw.png"),
        "errors": load_img("assets/gauges/errors.png"),
        "kw arc": load_img("assets/arcs/kw arc.png"),
        "speed arc": load_img("assets/arcs/speed arc.png"),
        "rpm arc": load_img("assets/arcs/rpm arc.png"),
        "battery arc green": load_img("assets/arcs/battery arc green.png"),
        "battery arc red": load_img("assets/arcs/battery arc red.png"),
        "battery icon off": load_img("assets/icons/battery off.png"),
        "battery icon on": load_img("assets/icons/battery on.png"),
        "satellite icon off": load_img("assets/icons/satellite off.png"),
        "satellite icon on": load_img("assets/icons/satellite on.png"),
        "brakes icon off": load_img("assets/icons/brakes off.png"),
        "brakes icon on": load_img("assets/icons/brakes on.png"),
        "engine icon off": load_img("assets/icons/engine off.png"),
        "engine icon blue": load_img("assets/icons/engine blue.png"),
        "engine icon red": load_img("assets/icons/engine red.png"),
        "chip icon off": load_img("assets/icons/chip off.png"),
        "chip icon blue": load_img("assets/icons/chip blue.png"),
        "chip icon red": load_img("assets/icons/chip red.png"),
        "switch icon off": load_img("assets/icons/switch off.png"),
        "switch icon blue": load_img("assets/icons/switch blue.png"),
        "switch icon red": load_img("assets/icons/switch red.png"),
        "oil change off": load_img("assets/icons/oil change off.png"),
        "oil change red": load_img("assets/icons/oil change red.png"),
        "borto left": load_img("assets/gauges/borto left.png"),
        "borto right": load_img("assets/gauges/borto right.png"),
        "borto bar green": load_img("assets/arcs/borto bar green.png"),
        "borto bar red": load_img("assets/arcs/borto bar red.png"),
    }
    icon_keys = [
        "battery icon off", "battery icon on",
        "brakes icon off", "brakes icon on",
        "satellite icon off", "satellite icon on",
        "engine icon off", "engine icon red", "engine icon blue",
        "chip icon off", "chip icon red", "chip icon blue",
        "switch icon off", "switch icon red", "switch icon blue",
        "oil change off", "oil change red",
    ]
    for key in icon_keys:
        icon = assets[key]
        assets[f"{key} small"] = pygame.transform.smoothscale(
            icon,
            (max(1, icon.get_width() // 2), max(1, icon.get_height() // 2)),
        )

    colors = {
        "bg": pygame.Color(10, 10, 12),
        "ring_dim": pygame.Color(27, 27, 27),
        "tick": pygame.Color(230, 230, 230),
        "bar": pygame.Color(220, 30, 30),
        "bar_kw": pygame.Color(220, 30, 30),
        "bar_battery": pygame.Color(40, 200, 120),
        "text": pygame.Color(235, 235, 235),
        "text_big": pygame.Color(245, 245, 245),
        "text_blue": pygame.Color(0x1B, 0x54, 0xFF),
        "text_red": pygame.Color(0xE6, 0x18, 0x18),
    }

    font = pygame.font.Font(None, 20)
    font_tiny = pygame.font.Font(None, 22)
    font_bar_label = pygame.font.Font(None, 29)
    font_large = pygame.font.Font(None, 50)
    font_voltage = pygame.font.Font(None, 40)
    font_gauge = pygame.font.Font(None, 30)
    font_speed = pygame.font.Font(None, 90)
    font_kw = pygame.font.Font(None, 50)
    font_rpm = pygame.font.Font(None, 50)
    font_battery = pygame.font.Font(None, 50)

    # Gauge sweep across the top: vmin at down-left, vmax at down-right
    # Achieved by CW direction from 225° to 315° (i.e., -45°).
    GAUGE_START_DEG = 225
    GAUGE_END_DEG = 315
    SPEED_MASK_START_DEG = 315
    SPEED_BASE_START_DEG = 225
    SPEED_DEG_PER_UNIT = 12.6  # degrees per 1 speed unit
    SPEED_VISIBLE_MAX = 16.0
    
    SPEED_START_DEG = SPEED_MASK_START_DEG
    SPEED_END_DEG = SPEED_START_DEG + (SPEED_VISIBLE_MAX * SPEED_DEG_PER_UNIT)
    RPM_MASK_START_DEG = 226
    RPM_BASE_START_DEG = -45
    RPM_DEG_PER_UNIT = SPEED_DEG_PER_UNIT / 500.0
    RPM_VISIBLE_MAX = 9000.0
    RPM_MAX_VALUE = 7000.0
    RPM_START_DEG = RPM_MASK_START_DEG
    RPM_END_DEG = RPM_START_DEG - (RPM_VISIBLE_MAX * RPM_DEG_PER_UNIT)
    KW_DEG_PER_UNIT = 14  # degrees per 1 kW
    KW_VISIBLE_MAX = 11.0
    KW_BASE_START_DEG = 260
    KW_MASK_START_DEG = 315
    KW_START_DEG = KW_BASE_START_DEG
    KW_END_DEG = KW_START_DEG + (KW_VISIBLE_MAX * KW_DEG_PER_UNIT)

    RPM_RANGE = (0.0, RPM_MAX_VALUE)
    POWER_RANGE = (0.0, 20.0)
    BATTERY_RANGE = (0.0, 100.0)
    BATTERY_DEG_PER_UNIT = 1.375
    BATTERY_VISIBLE_MAX = 101.0
    BATTERY_MAX_VALUE = 100.0
    BATTERY_BASE_START_DEG = 272
    BATTERY_MASK_START_DEG = 225
    BATTERY_START_DEG = BATTERY_BASE_START_DEG
    BATTERY_END_DEG = BATTERY_START_DEG - (BATTERY_VISIBLE_MAX * BATTERY_DEG_PER_UNIT)
    SPEED_RANGE = (0.0, SPEED_MAX_VALUE)
    SPEED_END_DEG = SPEED_START_DEG + (SPEED_VISIBLE_MAX * SPEED_DEG_PER_UNIT)
    DEBUG_FORCE_FULL_ARCS = False

    # Dummy values (replace later with CAN/GPS)
    power = 0.0
    rpm = 0.0
    speed = 0.0
    battery = 0.0
    power_arc = None
    rpm_arc = None
    speed_arc = None
    battery_arc = None
    engine_value = 0
    chip_value = 60
    switch_value = 0
    dc_current = 200
    ac_current = 200
    battery_voltage = 50
    battery_state = "on"
    brakes_state = "on"
    satellite_state = "on"
    engine_state = "red"
    chip_state = "blue"
    switch_state = "red"
    thruster_pct = 0.0
    thruster_arc = None
    borto_pct = 0.0
    borto_arc = None

    _beep = _generate_beep()
    _prev_alerts: set = set()
    _beep_cooldown = 0.0

    _error_idx = 0
    _error_t = 0.0
    _ERROR_CYCLE_SEC = 2.0

    _dim_surf = pygame.Surface((screen.get_width(), screen.get_height()))
    _dim_surf.fill((0, 0, 0))
    _dim_surf.set_alpha(89)  # 35%
    _daytime_cache = True
    _daytime_check_t = 0.0

    _moon_r = sc.s(18)
    _moon_surf = pygame.Surface((_moon_r * 3, _moon_r * 3), pygame.SRCALPHA)
    _moon_color = pygame.Color(200, 200, 160)
    pygame.draw.circle(_moon_surf, _moon_color, (_moon_r, _moon_r), _moon_r)
    pygame.draw.circle(_moon_surf, pygame.Color(0, 0, 0, 255), (_moon_r + _moon_r // 3, _moon_r - _moon_r // 6), int(_moon_r * 0.85))

    running = True
    while running:
        dt = clock.tick(FPS) / 1000.0

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                running = False
        # ----------------------------
        state = reader.snapshot()

        rpm = state.rpm

        speed_kph = state.speed_kph
        # Map real speed (kph) -> your gauge units (0..12)
        speed = (speed_kph / SPEED_FULL_SCALE_KPH) * 12.0
        # Map real kW -> gauge units (full scale = 8.0 gauge units on the image)
        power = (state.power_kw / KW_FULL_SCALE_KW) * 8.0
        battery = state.battery_pct
        power_arc = smooth_toward(power_arc, power, dt, GAUGE_ARC_SMOOTH_TAU_SEC)
        rpm_arc = smooth_toward(rpm_arc, rpm, dt, GAUGE_ARC_SMOOTH_TAU_SEC)
        speed_arc = smooth_toward(speed_arc, speed, dt, SPEED_ARC_SMOOTH_TAU_SEC)
        battery_arc = smooth_toward(battery_arc, battery, dt, BATTERY_ARC_SMOOTH_TAU_SEC)

        thruster_pct = state.thruster_pct
        thruster_arc = smooth_toward(thruster_arc, thruster_pct, dt, BATTERY_ARC_SMOOTH_TAU_SEC)

        borto_pct = state.borto_pct
        borto_arc = smooth_toward(borto_arc, borto_pct, dt, BATTERY_ARC_SMOOTH_TAU_SEC)

        dc_current = int(state.dc_current_a)
        ac_current = int(state.ac_current_a)
        battery_voltage = int(state.battery_voltage_v)

        battery_state = state.battery_state
        brakes_state = state.brakes_state
        satellite_state = state.satellite_state
        reverse_active = state.reverse_active

        engine_state = state.engine_state
        chip_state = state.chip_state
        switch_state = state.switch_state

        engine_value = int(state.engine_temp_c)
        chip_value = int(state.controller_temp_c)
        switch_value = float(state.switch_value_v)

        _error_t += dt
        _beep_cooldown = max(0.0, _beep_cooldown - dt)
        current_alerts: set = set(state.errors)
        if state.engine_state == "red":
            current_alerts.add("_engine_red")
        if state.chip_state == "red":
            current_alerts.add("_chip_red")
        if state.battery_state == "on":
            current_alerts.add("_battery_low")
        if current_alerts - _prev_alerts and _beep_cooldown <= 0.0:
            _beep.play()
            _beep_cooldown = 5.0
        _prev_alerts = current_alerts

        runtime.tick(dt, switch_value >= 1.0)
        if reader.gps is not None:
            gps_logger.tick(state, reader.gps.snapshot())
        drive_handler.tick()

        adc_ch0_v = state.adc_ch0_v
        adc_ch1_v = state.adc_ch1_v
        adc_ch2_v = state.adc_ch2_v
        adc_ch3_v = state.adc_ch3_v
        adc_ch0_raw_v = state.adc_ch0_raw_v
        adc_ch1_raw_v = state.adc_ch1_raw_v
        adc_ch2_raw_v = state.adc_ch2_raw_v
        adc_ch3_raw_v = state.adc_ch3_raw_v

        # ---- Draw ----
        # 1) Background
        screen.fill((0, 0, 0))

        screen.blit(assets["bg"], (sc.off_x, sc.off_y))

        # 3) PNG positions in DESIGN coordinates (you provided these)
        rpm_pos = sc.pt(70, 84)
        kw_pos = sc.pt(490, 23)
        kwbg_pos = sc.pt(490, 23)
        speed_pos = sc.pt(1047, 84)

        # 3) Compute centers from the PNG rects (robust + no guessing)
        rpm_rect   = assets["rpm"].get_rect(topleft=rpm_pos)
        speed_rect = assets["speed"].get_rect(topleft=speed_pos)
        kw_rect    = assets["kw"].get_rect(topleft=kw_pos)

        rpm_center_px = rpm_rect.center
        speed_center_px = speed_rect.center
        kw_center_px = kw_rect.center
        rpm_center_design = screen_px_to_design(sc, rpm_center_px)
        speed_center_design = screen_px_to_design(sc, speed_center_px)
        kw_center_design = screen_px_to_design(sc, kw_center_px)

        def blit_centered(image: pygame.Surface, center_design: tuple[float, float]) -> None:
            center_px = sc.pt(center_design[0], center_design[1])
            rect = image.get_rect(center=center_px)
            screen.blit(image, rect.topleft)

        def blit_arc_image(
            image: pygame.Surface,
            center_design: tuple[float, float],
            value: float,
            vmin: float,
            vmax: float,
            start_deg: float,
            end_deg: float,
            direction: str,
            mask_start_deg: float | None = None,
            base_start_deg: float | None = None,
        ) -> None:
            v = clamp(value, vmin, vmax)
            t = 0.0 if vmax == vmin else (v - vmin) / (vmax - vmin)
            full_circle = ((end_deg - start_deg) % 360.0) == 0.0 and end_deg != start_deg

            if t <= 0.0:
                start_anchor_deg = mask_start_deg if mask_start_deg is not None else start_deg
                if base_start_deg is not None and base_start_deg != start_anchor_deg:
                    base_rad = math.radians(base_start_deg)
                    start_rad = math.radians(start_anchor_deg)
                    base_masked = mask_arc_image(image, base_rad, start_rad, direction)
                    blit_centered(base_masked, center_design)
                return
            if full_circle and t >= 0.999:
                blit_centered(image, center_design)
                return

            if DEBUG_FORCE_FULL_ARCS:
                t = 1.0

            start_anchor_deg = mask_start_deg if mask_start_deg is not None else start_deg
            start_rad = math.radians(start_anchor_deg)

            if base_start_deg is not None and base_start_deg != start_anchor_deg:
                base_rad = math.radians(base_start_deg)
                base_masked = mask_arc_image(image, base_rad, start_rad, direction)
                blit_centered(base_masked, center_design)

            raw_sweep = (start_deg - end_deg) if direction.lower() == "cw" else (end_deg - start_deg)
            sweep_deg = raw_sweep % 360.0
            if sweep_deg == 0.0 and raw_sweep != 0.0:
                sweep_deg = 360.0

            sweep_rad = math.radians(sweep_deg) * t
            if direction.lower() == "cw":
                curr_rad = start_rad - sweep_rad
            else:
                curr_rad = start_rad + sweep_rad

            masked = mask_arc_image(image, start_rad, curr_rad, direction)
            blit_centered(masked, center_design)

        def draw_text_under_icon(text: str, icon_rect: pygame.Rect, color: pygame.Color) -> None:
            rendered = font.render(text, True, color)
            if rendered.get_width() <= 0:
                return
            text_w = icon_rect.width
            text_h = rendered.get_height()
            text_surface = pygame.Surface((text_w, text_h), pygame.SRCALPHA)
            text_surface.blit(
                rendered,
                rendered.get_rect(center=(text_w // 2, text_h // 2)).topleft,
            )
            text_rect = text_surface.get_rect(
                midtop=(icon_rect.centerx, icon_rect.bottom + sc.s(8)),
            )
            screen.blit(text_surface, text_rect.topleft)

        def draw_centered_text(
            text: str,
            center_design: tuple[float, float],
            color: pygame.Color,
            use_font: pygame.font.Font | None = None,
        ) -> None:
            render_font = font_large if use_font is None else use_font
            rendered = render_font.render(text, True, color)
            rect = rendered.get_rect(center=sc.pt(center_design[0], center_design[1]))
            screen.blit(rendered, rect.topleft)


        # Radii/thickness in DESIGN units (tweak once and it scales everywhere).
        RPM_RADIUS = 330
        KW_RADIUS = 392
        SPEED_RADIUS = 330
        BAR_THICKNESS = 117  # design units
        RPM_BAR_THICKNESS = 118  # design units
        KW_BAR_THICKNESS = 140  # design units (approx pixels at 1.0 scale)
        KW_CENTER_OFFSET = (0.0, 0.0)  # design units (positive Y = down)
        BATTERY_CENTER_OFFSET = (0.0, 0.0)  # design units (positive Y = down)

        # 4) Draw RPM arc image under the RPM gauge art
        blit_arc_image(
            assets["rpm arc"],
            (rpm_center_design[0] - 19.0, rpm_center_design[1] + 7.0),
            min(rpm_arc, RPM_VISIBLE_MAX), 0.0, RPM_VISIBLE_MAX,
            RPM_START_DEG, RPM_END_DEG,
            "cw",
            mask_start_deg=RPM_MASK_START_DEG,
            base_start_deg=RPM_BASE_START_DEG,
        )
        screen.blit(assets["rpm"], rpm_pos)

        # 5) Draw speed arc image under the speed gauge art
        
        blit_arc_image(
            assets["speed arc"],
            (speed_center_design[0] + 12.0, speed_center_design[1] + 2.0),
            min(speed_arc, SPEED_VISIBLE_MAX), 0.0, SPEED_VISIBLE_MAX,
            SPEED_START_DEG, SPEED_END_DEG,
            "ccw",
            mask_start_deg=SPEED_MASK_START_DEG,
            base_start_deg=SPEED_BASE_START_DEG,
        )
        screen.blit(assets["speed"], speed_pos)

        # 6) Draw kw background mask (blocks overlaps)
        screen.blit(assets["kwbg"], kwbg_pos)

        # 7) Draw KW arc images (above kwbg, below kw ticks because kw is drawn next)
        blit_arc_image(
            assets["kw arc"],
            (kw_center_design[0] + 21.0, kw_center_design[1] + 10.0),
            min(power_arc, KW_VISIBLE_MAX), 0.0, KW_VISIBLE_MAX,
            KW_START_DEG, KW_END_DEG,
            "ccw",
            mask_start_deg=KW_MASK_START_DEG,
            base_start_deg=KW_BASE_START_DEG,
        )

        battery_arc_key = "battery arc red" if battery_arc <= 20.0 else "battery arc green"
        blit_arc_image(
            assets[battery_arc_key],
            (kw_center_design[0] - 15.0, kw_center_design[1] + 13.0),
            min(battery_arc, BATTERY_VISIBLE_MAX), 0.0, BATTERY_VISIBLE_MAX,
            BATTERY_START_DEG, BATTERY_END_DEG,
            "cw",
            mask_start_deg=BATTERY_MASK_START_DEG,
            base_start_deg=BATTERY_BASE_START_DEG,
        )

        # 7) Draw kw FOREGROUND last so its white indicators/ticks sit on top of the red bar
        screen.blit(assets["kw"], kw_pos)

        # 7) Battery gauge numbers
        draw_centered_text("0", (680, 765), colors["text"], font_gauge)
        draw_centered_text("20", (590, 609), colors["text"], font_gauge)
        draw_centered_text("40", (573, 426), colors["text"], font_gauge)
        draw_centered_text("60", (647, 260), colors["text"], font_gauge)
        draw_centered_text("80", (779, 145), colors["text"], font_gauge)

        # 7) RPM gauge numbers
        draw_centered_text("0", (233, 718), colors["text"], font_gauge)
        draw_centered_text("1", (150, 598), colors["text"], font_gauge)
        draw_centered_text("2", (130, 450), colors["text"], font_gauge)
        draw_centered_text("3", (178, 308), colors["text"], font_gauge)
        draw_centered_text("4", (275, 207), colors["text"], font_gauge)
        draw_centered_text("5", (406, 155), colors["text"], font_gauge)
        draw_centered_text("6", (550, 160), colors["text"], font_gauge)

        # 7) KW gauge numbers
        _kw_step = KW_FULL_SCALE_KW / 4
        draw_centered_text("0",                          (1222, 764), colors["text"], font_gauge)
        draw_centered_text(str(int(_kw_step)),           (1317, 608), colors["text"], font_gauge)
        draw_centered_text(str(int(_kw_step * 2)),       (1335, 420), colors["text"], font_gauge)
        draw_centered_text(str(int(_kw_step * 3)),       (1262, 254), colors["text"], font_gauge)
        draw_centered_text(str(int(KW_FULL_SCALE_KW)),   (1124, 138), colors["text"], font_gauge)

        # 7) Speed gauge numbers
        draw_centered_text("0", (1671, 720), colors["text"], font_gauge)
        draw_centered_text("2", (1752, 598), colors["text"], font_gauge)
        draw_centered_text("4", (1775, 451), colors["text"], font_gauge)
        draw_centered_text("6", (1727, 311), colors["text"], font_gauge)
        draw_centered_text("8", (1629, 209), colors["text"], font_gauge)
        draw_centered_text("10", (1500, 156), colors["text"], font_gauge)
        draw_centered_text("12", (1355, 164), colors["text"], font_gauge)

        # 7) Drive indicator centered on speed gauge
        drive_indicator = "P" if brakes_state == "on" else ("R" if reverse_active else "D")
        draw_centered_text(
            drive_indicator,
            (speed_center_design[0] + 100.0, speed_center_design[1]),
            colors["text"],
            font_speed,
        )

        # 7) DC/AC voltages centered on kwbg (DC above, AC below)
        draw_centered_text(
            f"DC {dc_current} A",
            (kw_center_design[0], kw_center_design[1] - 50.0),
            colors["text"],
        )
        draw_centered_text(
            f"AC {ac_current} A",
            (kw_center_design[0], kw_center_design[1] + 50.0),
            colors["text"],
        )

        # 7) Battery voltage centered below kwbg
        draw_centered_text(
            f"{battery_voltage} V",
            (kw_center_design[0], kw_center_design[1] + 200.0),
            colors["text"],
            font_voltage,
        )

        # 9) Brakes icon
        screen.blit(
            assets[f"brakes icon {brakes_state} small"],
            sc.pt(rpm_center_design[0] - 60.0, 620),
        )

        # 10) Satellite icon
        screen.blit(assets[f"satellite icon {satellite_state} small"], sc.pt(1450, 240))

        # 11) Switch icon 
        switch_pos = sc.pt(1450, 580)
        switch_rect = assets[f"switch icon {switch_state} small"].get_rect(topleft=switch_pos)
        screen.blit(assets[f"switch icon {switch_state} small"], switch_rect.topleft)
        switch_text_color = colors["text"]
        if switch_state == "blue":
            switch_text_color = colors["text_blue"]
        elif switch_state == "red":
            switch_text_color = colors["text_red"]
        elif switch_state == "off":
            switch_text_color = pygame.Color(0, 0, 0, 0)
        draw_text_under_icon(f"{switch_value:.2f} V", switch_rect, switch_text_color)

        # 12) Chip temperature icon
        chip_pos = sc.pt(rpm_center_design[0] - 60.0, 250)
        chip_rect = assets[f"chip icon {chip_state} small"].get_rect(topleft=chip_pos)
        screen.blit(assets[f"chip icon {chip_state} small"], chip_rect.topleft)
        chip_text_color = pygame.Color(55, 55, 55)
        if chip_state == "blue":
            chip_text_color = colors["text_blue"]
        elif chip_state == "red":
            chip_text_color = colors["text_red"]
        draw_text_under_icon(f"{chip_value} °C", chip_rect, chip_text_color)

        # 13) Motor temperature icon
        engine_center_px = sc.pt(rpm_center_design[0] - 200.0, rpm_center_design[1])
        engine_rect = assets[f"engine icon {engine_state} small"].get_rect(center=engine_center_px)
        screen.blit(assets[f"engine icon {engine_state} small"], engine_rect.topleft)
        engine_text_color = pygame.Color(55, 55, 55)
        if engine_state == "blue":
            engine_text_color = colors["text_blue"]
        elif engine_state == "red":
            engine_text_color = colors["text_red"]
        draw_text_under_icon(f"{engine_value} °C", engine_rect, engine_text_color)

        # 14) Oil change icon (center of RPM gauge, 20 design units left)
        if OIL_CHANGE_HOURS > 0:
            oil_key = "oil change red" if runtime.total_hours >= OIL_CHANGE_HOURS else "oil change off"
            oil_center_px = sc.pt(rpm_center_design[0] - 30.0, rpm_center_design[1])
            oil_rect = assets[f"{oil_key} small"].get_rect(center=oil_center_px)
            screen.blit(assets[f"{oil_key} small"], oil_rect.topleft)

        # 15) Borto gauges (bar under gauge face), 170 design units from kwbg center
        borto_left_center  = (kw_center_design[0] - 170, kw_center_design[1])
        borto_right_center = (kw_center_design[0] + 170, kw_center_design[1])
        if BAR_MODE in (2, 3):
            thruster_bar = "borto bar red" if thruster_arc <= 20.0 else "borto bar green"
            blit_centered(mask_bar_image(assets[thruster_bar], thruster_arc / 100.0), borto_left_center)
            blit_centered(assets["borto left"], borto_left_center)
        if BAR_MODE in (1, 3):
            borto_bar = "borto bar red" if borto_arc <= 20.0 else "borto bar green"
            blit_centered(mask_bar_image(assets[borto_bar], borto_arc / 100.0), borto_right_center)
            blit_centered(assets["borto right"], borto_right_center)

        bar_h = assets["borto bar green"].get_height()
        bar_w = assets["borto bar green"].get_width()
        bar_center_y = sc.pt(0, borto_left_center[1])[1]
        bar_top = bar_center_y - bar_h // 2
        bar_bottom = bar_center_y + bar_h // 2
        for label, frac in [("80", 0.2), ("60", 0.4), ("40", 0.6), ("20", 0.8)]:
            rendered = font_tiny.render(label, True, colors["text"])
            label_y = int(bar_top + frac * bar_h) + 1
            if BAR_MODE in (2, 3):
                cx = sc.pt(borto_left_center[0], 0)[0]
                screen.blit(rendered, rendered.get_rect(center=(cx, label_y)).topleft)
            if BAR_MODE in (1, 3):
                cx = sc.pt(borto_right_center[0], 0)[0]
                screen.blit(rendered, rendered.get_rect(center=(cx, label_y)).topleft)

        if BAR_MODE in (2, 3):
            cx_left = sc.pt(borto_left_center[0], 0)[0]
            fe = font_bar_label.render("Fe", True, colors["text"])
            screen.blit(fe, fe.get_rect(midbottom=(cx_left, bar_top - 4)).topleft)
            pct_l = font_bar_label.render("%", True, colors["text"])
            screen.blit(pct_l, pct_l.get_rect(midtop=(cx_left, bar_bottom + 4)).topleft)
        if BAR_MODE in (1, 3):
            cx_right = sc.pt(borto_right_center[0], 0)[0]
            pb = font_bar_label.render("Pb", True, colors["text"])
            screen.blit(pb, pb.get_rect(midbottom=(cx_right, bar_top - 4)).topleft)
            pct_r = font_bar_label.render("%", True, colors["text"])
            screen.blit(pct_r, pct_r.get_rect(midtop=(cx_right, bar_bottom + 4)).topleft)

        # 15) Errors overlay (centered at bottom)
        errors_rect = assets["errors"].get_rect(midbottom=sc.pt(DESIGN_W / 2, DESIGN_H - 10))
        screen.blit(assets["errors"], errors_rect.topleft)
        active_errors = state.errors if state.errors else []
        if active_errors:
            box_w = errors_rect.width - sc.s(24)
            pages, cur = [], []
            for err in active_errors:
                test = "   ".join(cur + [err])
                if font_gauge.size(test)[0] <= box_w:
                    cur.append(err)
                else:
                    if cur:
                        pages.append(cur)
                    cur = [err]
            if cur:
                pages.append(cur)
            if len(pages) > 1:
                if _error_t >= _ERROR_CYCLE_SEC:
                    _error_idx = (_error_idx + 1) % len(pages)
                    _error_t = 0.0
                page = pages[_error_idx % len(pages)]
            else:
                page = pages[0]
            err_text = "   ".join(page)
            rendered = font_gauge.render(err_text, True, colors["text_red"])
            r = rendered.get_rect(center=errors_rect.center)
            screen.blit(rendered, r.topleft)


        if not IS_PI:
            draw_centered_text(f"{state.power_kw:.1f} kW", (60, 20), colors["text"], font_gauge)

        # Trip / total runtime anchored to errors box top edge
        pad = sc.s(10)
        trip_surf = font_gauge.render(f"TRIP  {runtime.trip_str}", True, colors["text"])
        screen.blit(trip_surf, trip_surf.get_rect(bottomleft=(errors_rect.left + pad, errors_rect.top - pad)).topleft)
        total_surf = font_gauge.render(f"TOTAL  {runtime.total_str}", True, colors["text"])
        screen.blit(total_surf, total_surf.get_rect(bottomright=(errors_rect.right - pad, errors_rect.top - pad)).topleft)

        # Notification overlay
        notif = drive_handler.notification
        if notif:
            box_w, box_h = sc.s(DESIGN_W // 2), sc.s(DESIGN_H // 2)
            box_x = (screen.get_width()  - box_w) // 2
            box_y = (screen.get_height() - box_h) // 2
            pygame.draw.rect(screen, pygame.Color(0, 0, 0),       (box_x, box_y, box_w, box_h))
            pygame.draw.rect(screen, pygame.Color(255, 255, 255),  (box_x, box_y, box_w, box_h), sc.s(3))
            rendered = font_large.render(notif, True, pygame.Color(255, 255, 255))
            screen.blit(rendered, rendered.get_rect(center=(box_x + box_w // 2, box_y + box_h // 2)).topleft)

        _daytime_check_t += dt
        if not IS_PI:
            if _daytime_check_t >= 5.0:
                _daytime_check_t = 0.0
                _daytime_cache = not _daytime_cache
        elif _daytime_check_t >= 60.0:
            _daytime_check_t = 0.0
            if state.latitude != 0.0 or state.longitude != 0.0:
                _daytime_cache = _is_daytime(state.latitude, state.longitude, state.gps_utc)
        if not _daytime_cache:
            screen.blit(_dim_surf, (0, 0))
            screen.blit(_moon_surf, _moon_surf.get_rect(topright=(screen.get_width() - sc.s(10), sc.s(10))).topleft)

        pygame.display.flip()

    runtime.save()
    gps_logger.close()
    pygame.quit()
    sys.exit(0)


if __name__ == "__main__":
    class _LocalMockReader:
        def snapshot(self):
            class S:
                power_kw = 5.0
                rpm = 1200.0
                speed_kph = 25.0
                battery_pct = 80.0
                dc_current_a = 20.0
                ac_current_a = 10.0
                battery_voltage_v = 52.0
                battery_state = "on"
                brakes_state = "off"
                satellite_state = "on"
                reverse_active = False
                engine_state = "blue"
                chip_state = "blue"
                switch_state = "blue"
                engine_temp_c = 45.0
                controller_temp_c = 40.0
                switch_value_v = 12.5
                errors = []
                borto_pct = 50.0
                borto_raw_v = 2.5
                thruster_pct = 50.0
                thruster_raw_v = 2.5
                adc_ch0_v = 2.5
                adc_ch1_v = 0.02
                adc_ch2_v = 2.5
                adc_ch3_v = 0.03
            return S()

    main(_LocalMockReader())
