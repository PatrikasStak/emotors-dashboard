#!/bin/bash
set -e

export DISPLAY=:0
export XAUTHORITY=/home/pi/.Xauthority

LOG=/tmp/dashboard_autostart.log
echo "----- $(date) start_dashboard_gui.sh -----" >> "$LOG"

# Wait until X really responds
for i in {1..30}; do
  xdpyinfo >/dev/null 2>&1 && break
  sleep 1
done

# Hide desktop so pygame fullscreen has a clean surface
lxpanelctl exit >/dev/null 2>&1 || true
pcmanfm --desktop-off >/dev/null 2>&1 || true
sleep 1

cd /home/pi/EmotorsDashboard

exec /home/pi/EmotorsDashboard/venv/bin/python app/main.py >> "$LOG" 2>&1
