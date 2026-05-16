import os
import sys
import platform
from Dashboard import main

_PID_FILE = "/tmp/emotors_dashboard.pid"

def _check_single_instance():
    if os.path.exists(_PID_FILE):
        try:
            pid = int(open(_PID_FILE).read().strip())
            os.kill(pid, 0)  # check if process is alive
            print(f"Dashboard already running (pid {pid}), exiting.")
            sys.exit(0)
        except (ProcessLookupError, ValueError):
            pass  # stale pid file
    with open(_PID_FILE, "w") as f:
        f.write(str(os.getpid()))

_check_single_instance()

IS_PI = (platform.system() == "Linux") and platform.machine().startswith(("arm", "aarch64"))

if IS_PI:
    from inputs.can_reader import CANReader
    from inputs.gps_reader import GPSReader
    from inputs.ina228_reader import INA228Reader
    from inputs.ads1115_reader import ADS1115Reader
    from inputs.combined_reader import CombinedReader
else:
    from inputs.mock_reader import MockReader


def run():
    if IS_PI:
        can = CANReader("can0", debug=True)
        ina = INA228Reader(debug=True)
        gps = GPSReader(device="/dev/ttyUSB0", baud=115200, debug=True)
        adc = ADS1115Reader(address=0x48, debug=True)

        can_started = False
        try:
            try:
                can.start()
                can_started = True
            except OSError as e:
                print(f"CAN noot ready: {e}")
                can = None  # <- important: CombinedReader must handle can=None

            gps.start()
            ina.start()
            adc.start()

            reader = CombinedReader(can, gps, ina, adc)
            main(reader)

        finally:
            # stop only what actually started
            if can_started and can is not None:
                can.stop()
            gps.stop()
            ina.stop()
            adc.stop()

    else:
        mock = MockReader()
        main(mock)

    try:
        os.remove(_PID_FILE)
    except Exception:
        pass


if __name__ == "__main__":
    run()
