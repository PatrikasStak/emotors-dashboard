#!/bin/bash
set -e

if [ "$EUID" -ne 0 ]; then
    echo "Run as root: sudo bash install.sh"
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

cp "$SCRIPT_DIR/emotors-tripreset.sh"  /usr/local/bin/emotors-tripreset.sh
cp "$SCRIPT_DIR/emotors-totalreset.sh" /usr/local/bin/emotors-totalreset.sh
cp "$SCRIPT_DIR/emotors-logsdrive.sh"  /usr/local/bin/emotors-logsdrive.sh
chmod +x /usr/local/bin/emotors-tripreset.sh
chmod +x /usr/local/bin/emotors-totalreset.sh
chmod +x /usr/local/bin/emotors-logsdrive.sh

cp "$SCRIPT_DIR/99-emotors.rules" /etc/udev/rules.d/99-emotors.rules

udevadm control --reload-rules
udevadm trigger

echo "Done. Plug in a drive to test."
