#!/bin/bash
set -e

if [ "$EUID" -ne 0 ]; then
    echo "Run as root: sudo bash install_service.sh"
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

cp "$SCRIPT_DIR/dashboard.service" /etc/systemd/system/dashboard.service
cp "$SCRIPT_DIR/can0-up.service" /etc/systemd/system/can0-up.service
chmod +x "$SCRIPT_DIR/run_pi.sh"

systemctl daemon-reload
systemctl enable can0-up.service
systemctl enable dashboard.service

echo "Done. Reboot to test, or run: sudo systemctl start dashboard.service"
