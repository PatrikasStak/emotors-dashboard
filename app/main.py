import platform
from Dashboard import main  # your big existing file

IS_PI = platform.system() == "Linux" and platform.machine().startswith("arm")

if IS_PI:
    from inputs.can_reader import CANReader
    from inputs.gps_reader import GPSReader
else:
    from inputs.mock_reader import MockReader

def run():
    if IS_PI:
        can = CANReader("can0")
        gps = GPSReader()
        can.start()
        gps.start()
        main(can)   # dashboard reads from CAN/GPS-backed reader
        can.stop()
        gps.stop()
    else:
        mock = MockReader()
        main(mock)  # dashboard reads simulated data

if __name__ == "__main__":
    run()
