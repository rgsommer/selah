#!/usr/bin/env bash
#
# Offline Selah demo — runs the slideshow against your LOCAL photos only.
#
# Everything that touches the network is disabled (email, Google Drive sync,
# motion, voice, web control) and your secrets file is stashed for the run, so
# nothing can log into Gmail or pop a Google OAuth window. Your real config and
# secrets are restored automatically when you quit (ESC or Ctrl-C).
#
set -e
cd "$(dirname "$0")"

PY=".venv/bin/python"
[ -x "$PY" ] || PY="python3"

REAL_CFG="display_config.json";  BAK_CFG="display_config.json.demobak"
REAL_SEC="secrets.local.json";   BAK_SEC="secrets.local.json.demobak"

restore() {
  [ -f "$BAK_CFG" ] && mv -f "$BAK_CFG" "$REAL_CFG"
  [ -f "$BAK_SEC" ] && mv -f "$BAK_SEC" "$REAL_SEC"
  echo "[demo] restored your real config."
}
trap restore EXIT INT TERM

# Stash real config + secrets so the demo can't reach Gmail/Drive.
cp -f "$REAL_CFG" "$BAK_CFG"
[ -f "$REAL_SEC" ] && mv -f "$REAL_SEC" "$BAK_SEC"

# Write an offline config (keeps your media paths, disables all network bits).
"$PY" - <<'PY'
import json
cfg = json.load(open("display_config.json.demobak"))
cfg.update({
    "email_address": "", "email_password": "",
    "cloud_backup_enabled": False,
    "motion_detection_enabled": False, "motion_triggered_slideshow": False,
    "voice_control_enabled": False, "web_control_enabled": False,
    "enable_face_recognition": False, "weather_enabled": False,
    "calendar_display_enabled": False,
    "verse_display_enabled": True, "theme_enabled": True,
    "on_time": "00:00", "off_time": "23:59", "rotate_interval": 4,
})
json.dump(cfg, open("display_config.json", "w"), indent=2)
PY

echo "[demo] First launch indexes your photos (one-time; can take a minute for 12k+)."
echo "[demo] Starting Selah — press ESC to quit."
"$PY" main.py
