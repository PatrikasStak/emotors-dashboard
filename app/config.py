# app/config.py
import platform

IS_PI = platform.machine().startswith("arm")

FPS = 60
CAN_BITRATE = 250000

SPEED_UNIT = "kph"
SPEED_FULL_SCALE_KPH = 18.0
SPEED_MAX_VALUE = 12.0
