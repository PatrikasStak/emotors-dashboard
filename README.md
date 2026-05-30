# Emotors Dashboard

A fullscreen pygame instrument cluster for an electric boat/vehicle, designed to run on a Raspberry Pi connected to a KLS motor controller via CAN bus. Runs in mock mode on macOS for development.

## Hardware

- **Raspberry Pi** — runs the dashboard fullscreen
- **KLS motor controller** — connected via `can0` (250 kbps)
- **INA228** — DC power sensor over I2C
- **ADS1115** — 4-channel ADC over I2C (reads Borto and thruster battery voltages on CH0/CH3)
- **GPS receiver** — serial, `/dev/ttyUSB0` at 115200 baud (gpsd)

## Gauges and display

| Element | Data source |
|---|---|
| RPM arc | CAN (KLS controller) |
| Speed arc | GPS |
| Power (kW) arc | INA228 voltage × DC current |
| Battery % arc | INA228 voltage, idle-averaged |
| Borto (Pb) bar | ADS1115 CH0 — lead-acid SOC table |
| Thruster (Fe) bar | ADS1115 CH3 — lithium SOC table |
| DC / AC current | INA228 / CAN motor current |
| Motor temp | CAN |
| Controller temp | CAN |
| Drive indicator (P/D/R) | CAN brake + reverse flags |
| GPS satellite icon | gpsd fix |
| Error banner | CAN error codes + sensor staleness |
| Trip / Total runtime | Persisted in `app/runtime.json` |

The display automatically dims at night using a solar elevation calculation based on GPS coordinates.

## Project layout

```
app/
  main.py            — entry point; auto-detects Pi vs. Mac
  Dashboard.py       — pygame render loop
  config.py          — speed scale, FPS, bar mode, oil change reminder
  inputs/
    can_reader.py    — python-can CAN bus reader
    gps_reader.py    — gpsd GPS reader
    ina228_reader.py — INA228 power sensor
    ads1115_reader.py— ADS1115 ADC reader
    combined_reader.py — merges all sensors into DashboardState
    mock_reader.py   — simulated data for development on macOS
  state/
    dashboard_state.py — shared data snapshot dataclass
    runtime_tracker.py — trip/total hour tracking
    gps_logger.py    — logs GPS track to CSV
    drive_handler.py — USB drive actions (log export, runtime reset)
assets/              — PNG gauge faces, arc overlays, status icons
scripts/
  run_pi.sh          — launch script for Pi
  run_mac.sh         — launch script for macOS
  udev/              — udev rules for USB drive triggers
```

## Setup

### Raspberry Pi

```bash
pip install -r requirements-pi.txt
```

Enable CAN interface:
```bash
sudo ip link set can0 up type can bitrate 250000
```

Run:
```bash
./scripts/run_pi.sh
```

To autostart on boot, call `run_pi.sh` from a systemd service or `.bashrc` with a display set.

### macOS (development)

```bash
python -m venv venv && source venv/bin/activate
pip install -r requirements-mac.txt
python app/main.py
```

Mock data is used automatically when not running on a Pi. Press `Esc` to exit.

## Configuration (`app/config.py`)

| Variable | Default | Description |
|---|---|---|
| `FPS` | 60 | Render frame rate |
| `CAN_BITRATE` | 250000 | CAN bus speed |
| `SPEED_FULL_SCALE_KPH` | 12.0 | GPS speed at full gauge deflection |
| `SPEED_MAX_VALID_KPH` | 20.0 | GPS readings above this are discarded |
| `KW_FULL_SCALE_KW` | 20.0 | Power at full gauge deflection |
| `BAR_MODE` | 3 | `0` = none, `1` = Borto only, `2` = thruster only, `3` = both |
| `OIL_CHANGE_HOURS` | 0 | Hours before oil-change reminder; `0` = disabled |

## USB drive actions

Plug in a USB drive with one of these volume labels to trigger an action while the dashboard is running:

| Label | Action |
|---|---|
| `TRIPRESET` | Reset trip runtime counter |
| `TOTALRESET` | Reset total runtime counter |
| `LOGSDRIVE` | Export GPS CSV logs to the drive |

Install the udev rules once on the Pi:
```bash
sudo ./scripts/udev/install.sh
```
