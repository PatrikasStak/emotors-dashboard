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

# The CAN controller's reported battery voltage reads ~1V high vs. a multimeter.
BATTERY_VOLTAGE_OFFSET_V = -1.0

# This boat's motor is wired/mounted so its rotation is physically reversed -
# the controller's forward/reverse command bit ends up backwards relative to
# actual boat motion. Set True to swap which gear the dashboard shows (R/D).
INVERT_GEAR_DIRECTION = True

# Physical trip/total reset button (replaces the USB-flashdrive reset flow).
# Wire one leg of the button to this GPIO pin (BCM numbering) and the other
# leg to any GND pin on the Pi - the pin is configured with an internal
# pull-up, so no external resistor is needed. Avoid pins already claimed by
# I2C (2, 3) or the CAN HAT's SPI/interrupt lines (7, 8, 9, 10, 11, 25).
# Short press = reset trip. Press and hold = reset total.
RESET_BUTTON_GPIO_PIN = 17
RESET_BUTTON_LONG_PRESS_SEC = 30.0
# A press is confirmed once the pin reads "pressed" continuously for this long.
RESET_BUTTON_PRESS_CONFIRM_SEC = 0.03
# A release is only confirmed once the pin reads "not pressed" continuously for
# this long, so a brief noise glitch mid-hold can't be mistaken for a release
# and cut the hold short.
RESET_BUTTON_RELEASE_CONFIRM_SEC = 0.2
