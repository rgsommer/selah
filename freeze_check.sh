#!/usr/bin/env bash
# Run this the moment the screen is FROZEN (while you can still SSH in). It
# captures what's stuck, then dumps the Python stack (which restarts Selah).
# If you CANNOT ssh in at all when it's frozen, that itself means the whole Pi
# is locked up -> the SD card, essentially confirmed.
cd "$(dirname "$0")"
PID=$(pgrep -f "python3 -u main.py" | head -1)

echo "======================================================================"
echo "  FREEZE CHECK  $(date '+%Y-%m-%d %H:%M:%S')"
echo "======================================================================"
echo
echo "--- uptime / load ---"
uptime
echo
echo "--- Selah process state (STAT + what it's blocked in) ---"
# STAT 'D' = uninterruptible sleep (stuck in kernel I/O, e.g. a failing SD card).
# WCHAN names the kernel function it's waiting in.
if [ -n "$PID" ]; then
    ps -o pid,stat,wchan:28,pcpu,pmem,etime,cmd -p "$PID"
else
    echo "  (main.py not running — it may have already died/restarted)"
fi
echo
echo "--- kernel log: I/O errors / hung tasks / OOM ---"
sudo dmesg 2>/dev/null | grep -iE "hung task|blocked for more than|I/O error|mmc[0-9]|EXT4-fs error|oom-kill|watchdog" | tail -25
echo "  (empty above = no storage/hang errors this boot)"
echo
if [ -n "$PID" ]; then
    echo "--- dumping Python stack (this RESTARTS Selah) ---"
    kill -ABRT "$PID"
    sleep 3
    tail -55 selah.log
fi
echo
echo "======================================================================"
echo "  Copy everything above and send it."
echo "  KEY: process STAT 'D' or an 'mmc'/'I/O error' line  = SD card."
echo "       stack stuck in image/file read                 = SD card."
echo "       stack in _sleep_pumping_toast (normal sleep)    = GPU/display."
echo "======================================================================"
