#!/bin/bash
#
# Selah Display System installer.
#
# Safe to run from the cloned repo (the normal path) or re-run later — it
# operates in its own directory, never overwrites existing config/secrets, and
# installs a systemd service pointed at wherever the repo actually lives.
#
set -e

echo "Starting Selah Display System installation..."

# Run in the directory this script lives in (the cloned repo), whatever it is.
SELAH_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SELAH_DIR"
SELAH_USER="$(whoami)"
echo "Installing into: $SELAH_DIR (service user: $SELAH_USER)"

# Update and install dependencies
sudo apt update
sudo apt install -y python3 python3-pip python3-dev python3-venv libatlas-base-dev \
    libopenjp2-7 libtiff5-dev libjpeg-dev libpng-dev zlib1g-dev libfreetype6-dev \
    liblcms2-dev libwebp-dev tcl8.6-dev tk8.6-dev python3-tk libportaudio2 \
    portaudio19-dev libopencv-dev python3-opencv vlc libvlc-dev python3-speechrecognition \
    python3-flask python3-requests python3-bs4 python3-google-auth python3-google-auth-oauthlib \
    python3-google-auth-httplib2 python3-pil

# Install Python packages
pip3 install --user pygame face_recognition Pillow google-api-python-client oauthlib requests-oauthlib qrcode

# Install Raspberry Pi camera support
sudo apt install -y libcamera-apps-lite
sudo raspi-config nonint do_camera 0 || true

# Create media directories
mkdir -p media/portrait media/landscape media/art media/display
mkdir -p modules
[ -f modules/__init__.py ] || touch modules/__init__.py

# --- Device-local config (never clobbered) ---------------------------------
# These are git-ignored; seed them from the tracked *.example templates so the
# repo never carries secrets and on-device edits survive every update.
[ -f display_config.json ] || cp display_config.example.json display_config.json
[ -f secrets.local.json ]  || cp secrets.local.json.example  secrets.local.json
[ -f special_days.json ]   || cp special_days.example.json   special_days.json
[ -f approved_senders.json ] || echo '["sender1@example.com"]' > approved_senders.json

# Runtime state files (created empty if absent)
[ -f leaderboard.json ]     || echo '{}' > leaderboard.json
[ -f quiz_scores.json ]     || echo '{}' > quiz_scores.json
[ -f media_log.json ]       || echo '[]' > media_log.json
[ -f error_log.json ]       || echo '[]' > error_log.json
[ -f calendar_events.json ] || echo '[]' > calendar_events.json

# Google OAuth client — placeholder only if the user hasn't supplied one.
if [ ! -f credentials.json ]; then
cat > credentials.json <<'EOL'
{
  "installed": {
    "client_id": "your_client_id",
    "project_id": "your_project_id",
    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
    "token_uri": "https://oauth2.googleapis.com/token",
    "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
    "client_secret": "your_client_secret",
    "redirect_uris": ["urn:ietf:wg:oauth:2.0:oob", "http://localhost"]
  }
}
EOL
fi

# --- systemd service (path- and user-aware) --------------------------------
SERVICE_TMP="$(mktemp)"
cat > "$SERVICE_TMP" <<EOF
[Unit]
Description=Selah Display System
After=network.target

[Service]
ExecStart=/usr/bin/python3 $SELAH_DIR/main.py
WorkingDirectory=$SELAH_DIR
Restart=always
User=$SELAH_USER

[Install]
WantedBy=multi-user.target
EOF
sudo cp "$SERVICE_TMP" /etc/systemd/system/selah_display.service
rm -f "$SERVICE_TMP"

# Enable and start service
sudo systemctl daemon-reload
sudo systemctl enable selah_display.service
sudo systemctl restart selah_display.service

# --- Auto-update timer (pulls from GitHub every ~15 min) -------------------
# Opt out with:  SELAH_NO_AUTOUPDATE=1 ./install_selah.sh   or   --no-autoupdate
AUTOUPDATE=1
for arg in "$@"; do
  [ "$arg" = "--no-autoupdate" ] && AUTOUPDATE=0
done
[ "${SELAH_NO_AUTOUPDATE:-0}" = "1" ] && AUTOUPDATE=0

if [ "$AUTOUPDATE" = "1" ]; then
  echo "Enabling auto-update (checks GitHub every ~15 min)..."
  chmod +x "$SELAH_DIR/deploy/selah-update.sh" 2>/dev/null || true

  # Update service — path/user-aware so it works wherever the repo lives.
  UPD_TMP="$(mktemp)"
  cat > "$UPD_TMP" <<EOF
[Unit]
Description=Selah auto-update (git pull + restart if changed)
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
User=$SELAH_USER
Environment=SELAH_DIR=$SELAH_DIR
Environment=SELAH_BRANCH=main
ExecStart=$SELAH_DIR/deploy/selah-update.sh
EOF
  sudo cp "$UPD_TMP" /etc/systemd/system/selah-update.service
  rm -f "$UPD_TMP"

  # Timer.
  sudo bash -c 'cat > /etc/systemd/system/selah-update.timer' <<'EOF'
[Unit]
Description=Run Selah auto-update periodically

[Timer]
OnBootSec=2min
OnUnitActiveSec=15min
Persistent=true

[Install]
WantedBy=timers.target
EOF

  # Let the service user restart Selah without a password (needed by the script).
  echo "$SELAH_USER ALL=(ALL) NOPASSWD: /usr/bin/systemctl restart selah_display.service" \
    | sudo tee /etc/sudoers.d/selah-update >/dev/null
  sudo chmod 440 /etc/sudoers.d/selah-update

  sudo systemctl daemon-reload
  sudo systemctl enable --now selah-update.timer
  echo "Auto-update enabled. (Disable later: sudo systemctl disable --now selah-update.timer)"
else
  echo "Auto-update NOT enabled (opted out). Enable later — see DEPLOY.md."
fi

echo ""
echo "Installation complete! Next steps:"
echo "1. Put your Gmail app password + weather key in: $SELAH_DIR/secrets.local.json"
echo "   (keep them OUT of display_config.json)."
echo "2. Replace credentials.json with your Google API OAuth client (calendar/drive)."
echo "3. Add birthdays/anniversaries to special_days.json (see special_days.example.json)."
echo "4. Place media in media/portrait, media/landscape, media/art, or media/display."
echo "5. Run 'python3 verify_install.py' to confirm everything is ready."
echo "6. Auto-update is ON — every push to GitHub reaches this Pi within ~15 min."
