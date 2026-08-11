# app/config.py
import platform

IS_PI = platform.system() == "Linux"

FPS = 60
CAN_BITRATE = 250000

SPEED_UNIT = "kph"
SPEED_FULL_SCALE_KPH = 12.0
SPEED_MAX_VALUE = 12.0 #dead code
GPS_MIN_SATELLITES = 20
KW_FULL_SCALE_KW = 20.0
RPM_FULL_SCALE = 3000.0  # real RPM that lines up with the gauge's printed max (6 = "x1000")

# 0 = no bars, 1 = borto only, 2 = thruster only, 3 = both
BAR_MODE = 1

# Oil change reminder. 0 = disabled, any positive number = hours until alert
OIL_CHANGE_HOURS = 0

# Propulsion battery pack (Li-ion), used for the projected-range estimate.
# Cell voltages below are common defaults for a 12S pack of standard NMC/LCO
# cells (4.2V max/cell) - fine as placeholders until the real pack is confirmed.
PACK_SERIES_CELLS = 12
PACK_CELL_MAX_V = 4.2   # full charge, per cell
PACK_CELL_NOM_V = 3.7   # nominal, per cell
PACK_CELL_MIN_V = 3.0   # safe low cutoff, per cell (protects cycle life)

# Rated capacity of the pack in Amp-hours. There's no "common" value for this -
# it's specific to the actual cells/pack the builder used. Range estimation stays
# disabled (range_km == None) until this is set.
PACK_CAPACITY_AH = None
