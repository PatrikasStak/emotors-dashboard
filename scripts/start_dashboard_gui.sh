#!/bin/bash
set -e

export DISPLAY=:0
export XAUTHORITY=/home/pi/.Xauthority

LOG=/tmp/dashboard_autostart.log
echo "----- $(date) start_dashboard_gui.sh -----" >> "$LOG"
echo "USER=$USER DISPLAY=$DISPLAY XAUTHORITY=$XAUTHORITY" >> "$LOG"

# Single-instance guard: if autostart fires more than once (e.g. lxsession
# restarting during boot), the second invocation exits here instead of
# racing the first for /dev/ttyUSB0.
LOCKFILE=/tmp/dashboard_gui.lock
exec 9>"$LOCKFILE"
if ! flock -n 9; then
  echo "Dashboard already running (lock held by another instance), exiting." >> "$LOG"
  exit 0
fi

# Wait until X really responds
for i in {1..30}; do
  xdpyinfo >/dev/null 2>&1 && break
  sleep 1
done

cd /home/pi/EmotorsDashboard

# Kill desktop chrome
lxpanelctl exit >/dev/null 2>&1 || true
pcmanfm --desktop-off >/dev/null 2>&1 || true

# Wait until can0 is up in listen-only
for i in {1..20}; do
  ip -details link show can0 2>/dev/null | grep -q "LISTEN-ONLY" && break
  sleep 0.5
done

# Start dashboard
/home/pi/EmotorsDashboard/venv/bin/python app/main.py >> "$LOG" 2>&1 &
PID=$!

# Wait until the dashboard window exists
for i in {1..60}; do
  wmctrl -l | grep -F "Dashboard Base" >/dev/null 2>&1 && break
  sleep 0.5
done

# Force dashboard dominance
wmctrl -a "Dashboard Base" || true
wmctrl -r "Dashboard Base" -b add,fullscreen,above,sticky || true
wmctrl -r "Dashboard Base" -b add,skip_taskbar,skip_pager || true
wmctrl -r "Dashboard Base" -b remove,hidden || true

wait $PID
