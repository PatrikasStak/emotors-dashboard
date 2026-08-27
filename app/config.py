# app/config.py
import platform

IS_PI = platform.system() == "Linux"

FPS = 60
CAN_BITRATE = 250000

SPEED_UNIT = "kph"
SPEED_FULL_SCALE_KPH = 9.0
SPEED_MAX_VALUE = 12.0 #dead code
GPS_MIN_SATELLITES = 20
KW_FULL_SCALE_KW = 12.0
RPM_FULL_SCALE = 9000.0  # real RPM that lines up with the gauge's printed max (6 = "x1000")

# 0 = no bars, 1 = borto only, 2 = thruster only, 3 = both
BAR_MODE = 1

# Oil change reminder. 0 = disabled, any positive number = hours until alert
OIL_CHANGE_HOURS = 0

# This boat has no INA228 DC current/voltage sensor - motor current/voltage come
# from the CAN controller instead. Set True if one is ever wired in.
HAS_INA228 = False

# Propulsion battery pack (Li-ion, 12S), used for the projected-range estimate.
PACK_SERIES_CELLS = 12
PACK_CELL_MAX_V = 4.2   # full charge, per cell (~50.4V pack)
PACK_CELL_NOM_V = 3.7   # nominal, per cell (44.4V pack)
PACK_CELL_MIN_V = 3.0   # safe low cutoff, per cell (protects cycle life) - not yet confirmed

PACK_CAPACITY_AH = 388.0

# This boat's motor is wired/mounted so its rotation is physically reversed -
# the controller's forward/reverse command bit ends up backwards relative to
# actual boat motion. Set True to swap which gear the dashboard shows (R/D).
INVERT_GEAR_DIRECTION = True
