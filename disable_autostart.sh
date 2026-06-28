#!/usr/bin/env bash
# Stop Selah from auto-launching and kill any running instance.
rm -f "$HOME/.config/autostart/selah.desktop"
pkill -f "python3 .*main.py" 2>/dev/null || true
echo "Autostart DISABLED and any running Selah stopped."
echo "(If an OLD autostart entry remains, list them with:  ls ~/.config/autostart/ )"
