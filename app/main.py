# app/main.py
from config import IS_PI
from dashboard import run_dashboard

if IS_PI:
    from io.can_reader import CANReader
    from io.gps_reader import GPSReader
else:
    from io.mock_reader import MockReader

def main():
    if IS_PI:
        can = CANReader("can0")
        gps = GPSReader()
        can.start()
        gps.start()

        run_dashboard(can, gps)

        can.stop()
        gps.stop()
    else:
        mock = MockReader()
        run_dashboard(mock)

if __name__ == "__main__":
    main()
