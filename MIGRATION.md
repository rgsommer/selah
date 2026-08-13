# Selah — Migrating to fresh storage (the SD-card fix)

The Pi was freezing hard (SSH froze too = whole-system I/O hang) and files were
corrupting — a **failing SD card**. This moves Selah to healthy storage. Budget
~45 minutes, most of it unattended copying.

## 1. Buy

Pick one (Raspberry Pi 5):
- **Best — NVMe SSD + M.2 HAT** (e.g. Pimoroni/official M.2 HAT + a 256 GB NVMe).
  No SD card at all; fastest and most reliable.
- **Simplest — high-endurance microSD**, 128 GB (Samsung PRO Endurance or
  SanDisk Max Endurance). Built for 24/7 writes, unlike the generic card.

Also confirm the **Pi 5 27 W USB-C supply** (rules power out for good).

## 2. Flash Raspberry Pi OS to the NEW drive

On any computer, use **Raspberry Pi Imager**:
- OS: Raspberry Pi OS (64-bit).
- In the gear/edit settings: set the **hostname**, your **user (`rsommer`)**,
  **Wi-Fi**, **locale/timezone (America/Toronto)**, and **enable SSH**.
- Write it to the NVMe (in a USB enclosure) or the new SD card.

For NVMe boot, also make sure the Pi's boot order includes NVMe
(`sudo raspi-config` → Advanced → Boot Order, or it usually just works on Pi 5).

## 3. First boot + basics

Boot the Pi on the new drive, SSH in, then:
```bash
sudo apt update && sudo apt full-upgrade -y
sudo apt install -y git python3-pip python3-pygame python3-pil \
    python3-opencv fonts-dejavu
pip3 install --user --break-system-packages qrcode google-api-python-client \
    google-auth-httplib2 google-auth-oauthlib pillow-heif httplib2 requests
```
(If any pip package is already provided by apt, that's fine — skip the error.)

## 4. Reinstall Selah

```bash
cd ~
git clone https://github.com/rgsommer/selah.git selah_display
cd selah_display
```

## 5. Copy your data + settings from the OLD card

Put the **old card** in a USB reader and plug it into the Pi. Find its mount
point (usually under `/media/rsommer/…`); call it `$OLD` below:
```bash
OLD=/media/rsommer/rootfs/home/rsommer/selah_display     # adjust to the real path
ls "$OLD"                                                # sanity check — should list Selah files
```

**Photos** (the big one):
```bash
rsync -a --info=progress2 "$OLD/media/" ~/selah_display/media/
```

**Settings + history** (gitignored, so not in the clone — don't skip these):
```bash
cd "$OLD"
for f in display_config.json secrets.local.json token.json credentials.json \
         approved_senders.json unapproved_senders.json contacts.json \
         sender_aliases.json leaderboard.json scheduled_media.json \
         special_days.json media_log.json processed_emails.json nudge_log.json \
         invite_log.json digest_log.json recent_shown.json quality_cache.json \
         forecast_cache.json calendar_cache.json precip_cache.json \
         drive_sync_state.json; do
  [ -f "$f" ] && cp "$f" ~/selah_display/
done
echo "settings copied"
```
> If the old card is too corrupted to read some files, that's OK — Selah
> recreates caches, and `restore_senders.py` / `rebuild_leaderboard.py` can
> rebuild the sender list and leaderboard from `media_log.json`.

## 6. Autostart + watchdog

**Autostart** (desktop session):
```bash
mkdir -p ~/.config/autostart
cp "$OLD/../.config/autostart/selah.desktop" ~/.config/autostart/ 2>/dev/null || \
cat > ~/.config/autostart/selah.desktop <<'EOF'
[Desktop Entry]
Type=Application
Name=Selah
Exec=/home/rsommer/selah_display/run.sh
X-GNOME-Autostart-enabled=true
EOF
chmod +x ~/selah_display/run.sh
```

**Hardware watchdog** (auto-recover any future hang):
```bash
sudo sed -i 's/^#*RuntimeWatchdogSec=.*/RuntimeWatchdogSec=15/' /etc/systemd/system.conf
sudo systemctl daemon-reexec
```

## 7. Launch + verify

```bash
cd ~/selah_display && ./run.sh          # watch it start; Ctrl-C to stop, or reboot
python3 folder_stats.py                 # confirms all photo folders are seen
python3 calendar_check.py               # calendar (if used)
python3 drive_check.py                  # Drive (if used)
```
Reboot once to confirm it autostarts on the new drive. Then check it stays up:
```bash
tail -5 ~/selah_display/restart_log.csv  # should stop gaining new rows
uptime -s                                # should hold steady for days
```

## Done

Keep the old card as a backup until you've confirmed a few days of stable
uptime, then wipe/retire it. If `restart_log.csv` stays quiet and `uptime`
climbs for days, the freezes are gone.
