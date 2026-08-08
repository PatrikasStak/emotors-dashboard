#!/bin/bash
set -e
cd "$(dirname "$0")/.."

# Render straight to the DRM/KMS framebuffer, no X11/desktop required.
# card0 is the v3d GPU (compute only, no display capability); card1 is vc4,
# the actual KMS display driver. SDL defaults to card0 and gives up instead
# of falling through, so point it at card1 explicitly.
export SDL_VIDEODRIVER=kmsdrm
export SDL_KMSDRM_DEVICE_INDEX=1

source venv/bin/activate

# Hand off from the boot splash without a black-screen gap: keep the last
# splash frame on screen until the dashboard draws its first real frame.
plymouth quit --retain-splash 2>/dev/null || true

python app/main.py >> /home/pi/dashboard.log 2>&1
