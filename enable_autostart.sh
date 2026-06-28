#!/usr/bin/env bash
# Make Selah launch automatically at desktop login, on the physical screen.
# (Desktop autostart is the reliable mechanism on Pi OS — it runs inside the
# graphical session where DISPLAY is set, unlike a bare systemd service.)
DIR="$(cd "$(dirname "$0")" && pwd)"
mkdir -p "$HOME/.config/autostart"
cat > "$HOME/.config/autostart/selah.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Selah Display
Exec=bash $DIR/run.sh
X-GNOME-Autostart-enabled=true
EOF
echo "Autostart ENABLED -> ~/.config/autostart/selah.desktop"
echo "Selah will launch at the next login / reboot."
echo ""
echo "Escape hatch (if it ever takes over the screen): SSH in and run"
echo "    bash $DIR/disable_autostart.sh"
