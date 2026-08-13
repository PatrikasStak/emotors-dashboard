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

# plymouthd runs as root, so an unprivileged 'plymouth quit' silently fails
# to actually terminate it, leaving it holding DRM master forever (which
# shows up as "Could not queue pageflip: -13" on every frame). Needs sudo.
sudo plymouth quit --retain-splash 2>/dev/null || true

# Wait for plymouthd to actually exit before grabbing kmsdrm ourselves --
# the quit command can return before the daemon has fully torn down.
for i in $(seq 1 30); do
    pgrep -x plymouthd >/dev/null || break
    sleep 0.1
done

python app/main.py >> /home/pi/dashboard.log 2>&1
