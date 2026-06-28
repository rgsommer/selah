#!/usr/bin/env bash
#
# Selah display diagnostics — run on the Pi (SSH is fine):
#   cd ~/selah_display && git pull && bash display_test.sh
#
# It forces DISPLAY=:0 (the physical desktop), reports what video driver pygame
# gets, flashes a green test window, and runs main.py briefly to capture its
# startup lines. Watch your screens during the GREEN BOX and main.py parts.
#
cd "$(dirname "$0")"
export DISPLAY="${DISPLAY:-:0}"
# Over SSH, point at the desktop session's X authority so we can reach :0.
if [ -z "$XAUTHORITY" ] && [ -f "$HOME/.Xauthority" ]; then
    export XAUTHORITY="$HOME/.Xauthority"
fi

echo "=================== DISPLAY ENV ==================="
echo "DISPLAY = $DISPLAY"
echo "XDG_SESSION_TYPE = ${XDG_SESSION_TYPE:-<unset>}"

echo "=================== MONITORS (xrandr) ==================="
xrandr --query 2>&1 | grep -E " connected| disconnected" || echo "(xrandr returned nothing)"

echo "=================== PYGAME VIDEO DRIVER ==================="
python3 - <<'PY' 2>&1 | tail -4
import pygame
pygame.init()
try:
    pygame.display.init()
    print("SDL video driver:", pygame.display.get_driver())
except Exception as e:
    print("display.init error:", e)
PY

echo "=================== GREEN BOX (look at the screen ~6s) ==================="
python3 - <<'PY' 2>&1 | tail -4
import pygame, time
pygame.init()
s = pygame.display.set_mode((800, 600))
print("green window driver:", pygame.display.get_driver(), "size:", s.get_size())
s.fill((0, 200, 0)); pygame.display.flip()
time.sleep(6)
print("green test done")
PY

echo "=================== main.py first lines (runs ~8s) ==================="
timeout 8 python3 main.py 2>&1 | head -22
echo "=================== END ==================="
echo "Reminder: tell me (1) did a GREEN box appear, (2) paste everything above,"
echo "(3) what was on the screens during the main.py part."
