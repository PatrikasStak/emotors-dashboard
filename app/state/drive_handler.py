from __future__ import annotations

import os
import subprocess
import threading
import time
from datetime import datetime, timezone

from config import (
    IS_PI,
    RESET_BUTTON_GPIO_PIN,
    RESET_BUTTON_LONG_PRESS_SEC,
    RESET_BUTTON_PRESS_CONFIRM_SEC,
    RESET_BUTTON_RELEASE_CONFIRM_SEC,
)

_FLAG_TRIPRESET  = "/tmp/emotors_TRIPRESET"
_FLAG_TOTALRESET = "/tmp/emotors_TOTALRESET"
_FLAG_LOGSDRIVE  = "/tmp/emotors_LOGSDRIVE"
_NOTIFICATION_DURATION = 3.0

_GPIO = None
if IS_PI:
    try:
        import RPi.GPIO as _GPIO
        _GPIO.setmode(_GPIO.BCM)
    except Exception as e:
        print(f"DriveHandler: RPi.GPIO unavailable, reset button disabled: {e}")
        _GPIO = None


class DriveHandler:
    def __init__(self, runtime, gps_logger):
        self._runtime = runtime
        self._gps_logger = gps_logger
        self._exporting = False
        self._notification_msg: str | None = None
        self._notification_until: float = 0.0

        self._btn_pressed = False
        self._btn_press_started = 0.0
        self._btn_long_fired = False
        self._btn_candidate: bool | None = None
        self._btn_candidate_since = 0.0
        self._btn_enabled = _GPIO is not None
        if self._btn_enabled:
            _GPIO.setup(RESET_BUTTON_GPIO_PIN, _GPIO.IN, pull_up_down=_GPIO.PUD_UP)

    @property
    def notification(self) -> str | None:
        if self._notification_msg and time.monotonic() < self._notification_until:
            return self._notification_msg
        return None

    def _notify(self, msg: str) -> None:
        self._notification_msg = msg
        self._notification_until = time.monotonic() + _NOTIFICATION_DURATION

    def _poll_reset_button(self) -> None:
        if not self._btn_enabled:
            return
        now = time.monotonic()
        try:
            raw_pressed = _GPIO.input(RESET_BUTTON_GPIO_PIN) == _GPIO.LOW
        except Exception as e:
            print(f"DriveHandler: reset button read error: {e}")
            return

        if raw_pressed == self._btn_pressed:
            # Matches the confirmed state - no pending transition, clear any
            # stale candidate from an earlier glitch that didn't pan out.
            self._btn_candidate = None
        else:
            if self._btn_candidate != raw_pressed:
                self._btn_candidate = raw_pressed
                self._btn_candidate_since = now
            # Confirming a release takes longer than confirming a press, so a
            # single noisy frame mid-hold can't masquerade as letting go.
            confirm_sec = RESET_BUTTON_PRESS_CONFIRM_SEC if raw_pressed else RESET_BUTTON_RELEASE_CONFIRM_SEC
            if now - self._btn_candidate_since >= confirm_sec:
                self._btn_pressed = raw_pressed
                self._btn_candidate = None
                if raw_pressed:
                    self._btn_press_started = now
                    self._btn_long_fired = False
                elif not self._btn_long_fired:
                    # Released before the long-press threshold -> short press.
                    self._runtime.reset_trip()
                    self._runtime.save()
                    self._notify("Trip Reset")
                    print("DriveHandler: trip reset (button)")
            return

        if self._btn_pressed and not self._btn_long_fired and (now - self._btn_press_started) >= RESET_BUTTON_LONG_PRESS_SEC:
            self._btn_long_fired = True
            self._runtime.reset_total()
            self._runtime.save()
            self._notify("Total Reset")
            print("DriveHandler: total reset (button)")

    def tick(self) -> None:
        self._poll_reset_button()

        try:
            if os.path.exists(_FLAG_TRIPRESET):
                os.remove(_FLAG_TRIPRESET)
                self._runtime.reset_trip()
                self._runtime.save()
                print("DriveHandler: trip reset")
        except Exception as e:
            print(f"DriveHandler TRIPRESET error: {e}")

        try:
            if os.path.exists(_FLAG_TOTALRESET):
                os.remove(_FLAG_TOTALRESET)
                self._runtime.reset_total()
                self._runtime.save()
                print("DriveHandler: total reset")
        except Exception as e:
            print(f"DriveHandler TOTALRESET error: {e}")

        if not self._exporting:
            try:
                if os.path.exists(_FLAG_LOGSDRIVE):
                    with open(_FLAG_LOGSDRIVE) as f:
                        devname = f.read().strip()
                    os.remove(_FLAG_LOGSDRIVE)
                    if devname:
                        self._exporting = True
                        threading.Thread(
                            target=self._export_logs, args=(devname,), daemon=True
                        ).start()
            except Exception as e:
                print(f"DriveHandler LOGSDRIVE error: {e}")

    def _write_engine_hours(self, dest_dir: str) -> None:
        try:
            ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
            line = f"Engine runtime (lifetime): {self._runtime.lifetime_str} ({self._runtime.lifetime_hours:.2f} hours) as of {ts}\n"
            with open(os.path.join(dest_dir, "engine_hours.txt"), "w") as f:
                f.write(line)
        except Exception as e:
            print(f"DriveHandler: engine_hours write error: {e}")

    def _find_mount_point(self, devname: str) -> str | None:
        try:
            with open("/proc/mounts") as f:
                for line in f:
                    parts = line.split()
                    if len(parts) >= 2 and parts[0] == devname:
                        return parts[1]
        except Exception:
            pass
        return None

    def _export_logs(self, devname: str) -> None:
        mounted_here = False
        try:
            mount_point = self._find_mount_point(devname)

            if not mount_point:
                result = subprocess.run(
                    ["udisksctl", "mount", "-b", devname],
                    capture_output=True, text=True, timeout=15,
                )
                if result.returncode != 0:
                    print(f"DriveHandler: mount failed: {result.stderr.strip()}")
                    return
                if " at " in result.stdout:
                    mount_point = result.stdout.split(" at ", 1)[1].strip().rstrip(".")
                mounted_here = True

            if not mount_point or not os.path.isdir(mount_point):
                print(f"DriveHandler: could not find mount point for {devname}")
                return

            self._gps_logger.export_and_clear(mount_point)
            self._write_engine_hours(mount_point)
            print(f"DriveHandler: logs exported to {mount_point}")
            self._notify("Logs Exported")

        except Exception as e:
            print(f"DriveHandler: export error: {e}")
        finally:
            if mounted_here:
                subprocess.run(["udisksctl", "unmount", "-b", devname], timeout=10)
            self._exporting = False
