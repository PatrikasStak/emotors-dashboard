#!/bin/bash
set -e
cd "$(dirname "$0")/.."
source venv/bin/activate
python app/main.py >> /home/pi/dashboard.log 2>&1