# app/config.py
import platform

IS_PI = platform.machine().startswith("arm")

FPS = 60
CAN_BITRATE = 250000
