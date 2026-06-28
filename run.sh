#!/usr/bin/env bash
# Launch Selah on the physical screen. Works from the desktop terminal or SSH
# (it forces DISPLAY=:0 and the X authority). Ctrl-C to stop.
cd "$(dirname "$0")"
export DISPLAY="${DISPLAY:-:0}"
if [ -z "$XAUTHORITY" ] && [ -f "$HOME/.Xauthority" ]; then
    export XAUTHORITY="$HOME/.Xauthority"
fi
# Stop X11 from blanking/sleeping the screens (Selah re-asserts this too).
xset s off 2>/dev/null; xset s noblank 2>/dev/null; xset -dpms 2>/dev/null
exec python3 main.py
