from __future__ import annotations

import os
import subprocess
import threading
import time
from datetime import datetime, timezone

_FLAG_TRIPRESET  = "/tmp/emotors_TRIPRESET"
_FLAG_TOTALRESET = "/tmp/emotors_TOTALRESET"
_FLAG_LOGSDRIVE  = "/tmp/emotors_LOGSDRIVE"
_NOTIFICATION_DURATION = 3.0


class DriveHandler:
    def __init__(self, runtime, gps_logger):
        self._runtime = runtime
        self._gps_logger = gps_logger
        self._exporting = False
        self._notification_msg: str | None = None
        self._notification_until: float = 0.0

    @property
    def notification(self) -> str | None:
        if self._notification_msg and time.monotonic() < self._notification_until:
            return self._notification_msg
        return None

    def _notify(self, msg: str) -> None:
        self._notification_msg = msg
        self._notification_until = time.monotonic() + _NOTIFICATION_DURATION

    def tick(self) -> None:
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
