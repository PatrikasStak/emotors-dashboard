#!/bin/bash
set -e
cd "$(dirname "$0")/.."

# Render straight to the DRM/KMS framebuffer, no X11/desktop required.
export SDL_VIDEODRIVER=kmsdrm

source venv/bin/activate

# Hand off from the boot splash without a black-screen gap: keep the last
# splash frame on screen until the dashboard draws its first real frame.
plymouth quit --retain-splash 2>/dev/null || true

# 'plymouth quit' returns before plymouthd has actually released the DRM
# master, so wait for it to fully exit before grabbing kmsdrm ourselves.
for i in $(seq 1 30); do
    pgrep -x plymouthd >/dev/null || break
    sleep 0.1
done

python app/main.py >> /home/pi/dashboard.log 2>&1