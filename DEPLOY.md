# Selah — Deployment & Auto-Update

Selah is a **native Python/pygame app** that runs locally on the Raspberry Pi
(camera, GPIO, dual HDMI, OpenCV, VLC). It is *not* a web app and cannot be
"opened from a URL" — but the Pi can **pull its own updates** from this git
repo, which is the practical version of that idea.

## First-time setup on the Pi

```bash
# 1. Clone (public repo — no auth needed)
cd ~
git clone https://github.com/rgsommer/selah.git selah_display
cd selah_display

# 2. Install system + Python deps
chmod +x install_selah.sh && ./install_selah.sh

# 3. Create device-local config from templates (these are git-ignored)
cp display_config.example.json display_config.json
cp secrets.local.json.example  secrets.local.json
cp special_days.example.json   special_days.json   # optional

# 4. Put real secrets in secrets.local.json (Gmail app pw, weather key, web pw)
#    — NOT in display_config.json. Or use env vars (SELAH_EMAIL_PASSWORD, etc).

# 5. Verify, then run
python3 verify_install.py
python3 main.py
```

## What is and isn't tracked in git

| Tracked (code/templates)         | Git-ignored (device-local)                         |
|----------------------------------|----------------------------------------------------|
| `*.py`, `modules/`, installer    | `display_config.json`, `secrets.local.json`        |
| `*.example.json`                 | `special_days.json`, `approved_senders.json`       |
| `deploy/`, docs                  | `media/`, `recordings/`, `token.json`, `*_cache`   |

Because device config is git-ignored, `git pull`/reset on the Pi **never**
clobbers on-device settings, secrets, birthdays, or photos.

## Auto-update (pull-based)

`deploy/selah-update.sh` fetches the chosen branch and, only if it changed,
hard-resets to it and restarts the service. Install the timer once:

```bash
sudo cp deploy/selah-update.service /etc/systemd/system/
sudo cp deploy/selah-update.timer   /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now selah-update.timer
```

Now every push to `main` lands on the Pi within ~15 minutes. Check status with
`systemctl status selah-update.timer` and logs with
`journalctl -u selah-update.service`.

> `sudo systemctl restart` inside the script requires the `pi` user to restart
> the service without a password. Add via `sudo visudo`:
> `pi ALL=(ALL) NOPASSWD: /usr/bin/systemctl restart selah_display.service`

## `curriculate.net/selah` install one-liner (optional)

Selah can't be *served* from curriculate.net, but that path can host the
installer so setup is one command. Point `curriculate.net/selah` at a script
that clones + runs `install_selah.sh`, then:

```bash
curl -sSL https://www.curriculate.net/selah | bash
```
