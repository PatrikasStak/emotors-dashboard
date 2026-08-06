#!/bin/bash
set -e
cd "$(dirname "$0")/.."

# Render straight to the DRM/KMS framebuffer, no X11/desktop required.
export SDL_VIDEODRIVER=kmsdrm

source venv/bin/activate
python app/main.py >> /home/pi/dashboard.log 2>&1