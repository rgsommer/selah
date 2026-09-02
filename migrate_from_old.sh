#!/usr/bin/env bash
# One-shot migration: copy Selah's data + settings from the OLD (failing) SD card
# into THIS fresh install. Run it ON the Pi booted from the NEW card, from inside
# the freshly-cloned selah_display (this script's folder is the destination).
#
#   ./migrate_from_old.sh /path/to/OLD/selah_display
#   ./migrate_from_old.sh /media/rsommer/rootfs/home/rsommer/selah_display
#
# Options:
#   --no-media       copy only settings/state (fast; skip the big photo copy)
#   --media-only     copy only the photo library (skip settings)
#
# Settings are copied FIRST (small, critical) so even if the dying card gives up
# during the big media copy, your config/senders/leaderboard/greetings survive.

set -uo pipefail
DEST="$(cd "$(dirname "$0")" && pwd)"

SRC=""; DO_MEDIA=1; DO_SETTINGS=1
for a in "$@"; do
    case "$a" in
        --no-media|--settings-only) DO_MEDIA=0 ;;
        --media-only)               DO_SETTINGS=0 ;;
        -*) echo "Unknown option: $a"; exit 1 ;;
        *)  SRC="$a" ;;
    esac
done

# The gitignored settings/state that are NOT in the repo clone and must be copied.
SETTINGS=(
    display_config.json secrets.local.json token.json credentials.json
    approved_senders.json unapproved_senders.json contacts.json
    sender_aliases.json leaderboard.json scheduled_media.json special_days.json
    media_log.json processed_emails.json nudge_log.json invite_log.json
    digest_log.json recent_shown.json drive_sync_state.json
    quality_cache.json forecast_cache.json calendar_cache.json precip_cache.json
)

find_candidates() {
    # Best-effort: Selah folders on any mounted card under /media/<user>.
    find /media/"$USER" -maxdepth 6 -type f -name main.py 2>/dev/null \
        | sed 's#/main.py$##' | grep -i selah || true
}

if [ -z "$SRC" ]; then
    echo "Usage: $0 /path/to/OLD/selah_display  [--no-media | --media-only]"
    echo
    echo "Find the old card's mount:   lsblk -f    then look under /media/$USER/"
    CANDS="$(find_candidates)"
    if [ -n "$CANDS" ]; then
        echo
        echo "Possible old Selah folders I found:"
        echo "$CANDS" | sed 's/^/   /'
    fi
    exit 1
fi

# --- validate ---
if [ ! -d "$SRC" ]; then
    echo "ERROR: source not found: $SRC"; exit 1
fi
if [ ! -f "$SRC/main.py" ] && [ ! -d "$SRC/media" ]; then
    echo "ERROR: '$SRC' doesn't look like a Selah folder (no main.py or media/)."
    exit 1
fi
if [ "$(cd "$SRC" && pwd)" = "$DEST" ]; then
    echo "ERROR: source and destination are the same folder ($DEST)."; exit 1
fi

echo "======================================================================"
echo "  Migrate Selah"
echo "    FROM (old card): $SRC"
echo "    TO   (new card): $DEST"
echo "======================================================================"
echo

# --- settings first (critical, tiny) ---
if [ "$DO_SETTINGS" = 1 ]; then
    echo "--- Copying settings / state ---"
    copied=0; missing=0
    for f in "${SETTINGS[@]}"; do
        if [ -f "$SRC/$f" ]; then
            if cp -p "$SRC/$f" "$DEST/$f" 2>/dev/null; then
                echo "   ok   $f"; copied=$((copied+1))
            else
                echo "   FAIL $f  (unreadable on the old card)"
            fi
        else
            missing=$((missing+1))
        fi
    done
    echo "   -> $copied copied, $missing not present on the old card."
    # Autostart entry (lives outside the selah folder).
    AUTO="$SRC/../.config/autostart/selah.desktop"
    if [ -f "$AUTO" ]; then
        mkdir -p "$HOME/.config/autostart"
        cp -p "$AUTO" "$HOME/.config/autostart/" 2>/dev/null \
            && echo "   ok   ~/.config/autostart/selah.desktop"
    fi
    chmod +x "$DEST/run.sh" 2>/dev/null || true
    echo
fi

# --- media (large; tolerate bad sectors on the dying card) ---
if [ "$DO_MEDIA" = 1 ]; then
    if [ -d "$SRC/media" ]; then
        echo "--- Copying photo library (skips unreadable files) ---"
        echo "   this can take a while; safe to leave running."
        rsync -a --info=progress2 --ignore-errors "$SRC/media/" "$DEST/media/"
        rc=$?
        n=$(find "$DEST/media" -type f 2>/dev/null | wc -l)
        echo "   -> media/ now has $n file(s).  (rsync exit $rc; non-zero usually"
        echo "      just means some files were unreadable and skipped.)"
    else
        echo "--- No media/ folder on the old card — skipping. ---"
    fi
    echo
fi

echo "======================================================================"
echo "  Done. Next:"
echo "    1) Sanity check:   python3 folder_stats.py"
echo "    2) Rebuild if the card dropped files:"
echo "         python3 restore_senders.py --all      # re-add senders from media_log"
echo "         python3 rebuild_leaderboard.py --apply"
echo "    3) Enable the watchdog + autostart (see MIGRATION.md), then reboot."
echo "    4) Launch now to test:   ./run.sh"
echo "======================================================================"
