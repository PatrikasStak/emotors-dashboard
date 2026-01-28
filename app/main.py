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

        can_started = False
        try:
            try:
                can.start()
                can_started = True
            except OSError as e:
                print(f"CAN not ready: {e}")
                can = None  # <- important: CombinedReader must handle can=None

            gps.start()

            reader = CombinedReader(can, gps)  # CombinedReader should accept can=None
            main(reader)

        finally:
            # stop only what actually started
            if can_started and can is not None:
                can.stop()
            gps.stop()

    else:
        mock = MockReader()
        main(mock)


if __name__ == "__main__":
    run()
