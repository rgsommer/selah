#!/usr/bin/env bash
# Launch Selah on the physical screen, with auto-restart and logging so a crash
# (even a C-level segfault) recovers in seconds and its cause is captured.
# Works from the desktop terminal or SSH (forces DISPLAY=:0 and X authority).
# Ctrl-C to stop; a clean ESC-quit (exit 0) also stops without restarting.
cd "$(dirname "$0")"
export DISPLAY="${DISPLAY:-:0}"
if [ -z "$XAUTHORITY" ] && [ -f "$HOME/.Xauthority" ]; then
    export XAUTHORITY="$HOME/.Xauthority"
fi
# Stop X11 from blanking/sleeping the screens (Selah re-asserts this too).
xset s off 2>/dev/null; xset s noblank 2>/dev/null; xset -dpms 2>/dev/null

# Dump a Python traceback even on a fatal C crash (SIGSEGV/SIGABRT).
export PYTHONFAULTHANDLER=1

LOG="$(pwd)/selah.log"
# Keep the log bounded (~5 MB) by trimming to the last 2000 lines on start.
if [ -f "$LOG" ] && [ "$(wc -c <"$LOG" 2>/dev/null || echo 0)" -gt 5000000 ]; then
    tail -n 2000 "$LOG" > "$LOG.tmp" 2>/dev/null && mv "$LOG.tmp" "$LOG"
fi

while true; do
    echo "=== Selah starting $(date '+%Y-%m-%d %H:%M:%S') ===" >> "$LOG"
    python3 -u main.py >> "$LOG" 2>&1
    code=$?
    echo "=== Selah exited (code $code) $(date '+%Y-%m-%d %H:%M:%S') ===" >> "$LOG"
    # Clean quit (ESC / normal return) -> stop. Any crash -> restart shortly.
    [ "$code" = "0" ] && break
    echo "    non-zero exit — restarting in 3s" >> "$LOG"
    sleep 3
done
