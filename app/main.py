import platform
from Dashboard import main  # your big existing file

IS_PI = platform.machine().startswith("arm")

if IS_PI:
    from io.can_reader import CANReader
    from io.gps_reader import GPSReader
else:
    from io.mock_reader import MockReader

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
