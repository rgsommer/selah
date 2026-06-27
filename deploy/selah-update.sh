#!/usr/bin/env bash
#
# Pull the latest Selah code and restart the service only if something changed.
# Intended to run on the Pi from a systemd timer (see selah-update.timer).
#
# Device-local files (display_config.json, secrets.local.json, special_days.json,
# approved_senders.json, media/, *_cache.json, token.json) are git-ignored, so
# this never touches on-device settings or photos.
#
set -euo pipefail

REPO_DIR="${SELAH_DIR:-$HOME/selah_display}"
BRANCH="${SELAH_BRANCH:-main}"
SERVICE="${SELAH_SERVICE:-selah_display.service}"

cd "$REPO_DIR"

git fetch --quiet origin "$BRANCH"
LOCAL="$(git rev-parse HEAD)"
REMOTE="$(git rev-parse "origin/$BRANCH")"

if [ "$LOCAL" = "$REMOTE" ]; then
  echo "[selah-update] already up to date (${LOCAL:0:8})"
  exit 0
fi

echo "[selah-update] updating ${LOCAL:0:8} -> ${REMOTE:0:8}"
# Hard-reset to the remote so a clean Pi never hits merge conflicts. Safe
# because everything device-specific is git-ignored (untracked files survive).
git reset --hard "origin/$BRANCH"

# Optional: re-run the verifier so a bad deploy is visible in the journal.
if [ -f verify_install.py ]; then
  python3 verify_install.py || echo "[selah-update] verify reported issues (continuing)"
fi

sudo systemctl restart "$SERVICE"
echo "[selah-update] restarted $SERVICE"
