#!/usr/bin/env bash
# Launch Selah on the physical screen. Works from the desktop terminal or SSH
# (it forces DISPLAY=:0 and the X authority). Ctrl-C to stop.
cd "$(dirname "$0")"
export DISPLAY="${DISPLAY:-:0}"
if [ -z "$XAUTHORITY" ] && [ -f "$HOME/.Xauthority" ]; then
    export XAUTHORITY="$HOME/.Xauthority"
fi
exec python3 main.py
