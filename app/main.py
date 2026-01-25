import platform
from Dashboard import main

IS_PI = (platform.system() == "Linux") and platform.machine().startswith(("arm", "aarch64"))

if IS_PI:
    from inputs.can_reader import CANReader
    from inputs.gps_reader import GPSReader
    from inputs.combined_reader import CombinedReader
else:
    from inputs.mock_reader import MockReader

def run():
    if IS_PI:
        can = CANReader("can0")
        gps = GPSReader()
        can.start()
        gps.start()
        reader = CombinedReader(can, gps)
        try:
            main(reader)
        finally:
            can.stop()
            gps.stop()
    else:
        mock = MockReader()
        main(mock)

if __name__ == "__main__":
    run()
