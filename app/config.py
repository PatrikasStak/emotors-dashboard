# app/config.py
import platform

IS_PI = platform.system() == "Linux"

FPS = 60
CAN_BITRATE = 250000

SPEED_UNIT = "kph"
SPEED_FULL_SCALE_KPH = 12.0
SPEED_MAX_VALUE = 12.0 #dead code
GPS_MIN_SATELLITES = 25
KW_FULL_SCALE_KW = 20.0

# 0 = no bars, 1 = borto only, 2 = thruster only, 3 = both
BAR_MODE = 3

# Oil change reminder. 0 = disabled, any positive number = hours until alert
OIL_CHANGE_HOURS = 0
