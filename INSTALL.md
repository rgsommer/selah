# Selah — Install Guide (Raspberry Pi 4)

Full setup, start to finish. **Bare minimum to see photos:** steps 1 → 5 (drop
some photos in) → 9. Steps 2–4 add email / Drive / calendar; the rest is
optional polish. After step 1, future updates are automatic.

See also: [DEPLOY.md](DEPLOY.md) for how auto-update works.

## 1. Clone + install
```bash
cd ~
git clone https://github.com/rgsommer/selah.git selah_display
cd selah_display
chmod +x install_selah.sh
./install_selah.sh
```
Installs all dependencies, creates the media folders, seeds config from the
`*.example` templates, installs the auto-start service, **and enables
auto-update** (every push to GitHub reaches the Pi within ~15 min). Opt out
with `./install_selah.sh --no-autoupdate` or `SELAH_NO_AUTOUPDATE=1 ./install_selah.sh`.

## 2. Secrets (kept out of the main config)
```bash
nano secrets.local.json
```
Fill in: `email_address`, `email_password` (a **freshly rotated** Gmail App
Password), `weather_api_key`, `web_control_password`.

## 3. Google OAuth — Calendar + Drive
- Google Cloud Console: enable **Calendar API** + **Drive API**, create an
  **OAuth Desktop** client, download as `credentials.json` into `~/selah_display/`.
- Authorize once to create `token.json`:
  ```bash
  python3 main.py        # consent in the browser popup, then press ESC
  ```
- Make sure that Google account is **subscribed to your family calendar** and
  has **access to the shared Drive folder(s)**.

## 4. Device settings
Easiest: copy your working `display_config.json` over (it has **no secrets** —
those live in `secrets.local.json`). Otherwise:
```bash
nano display_config.json
```
Set `timezone`, `on_time`/`off_time`, `google_calendar_id`,
`google_drive_folder_ids`. Everything is also editable on-screen via **F1**.

## 5. Photos (any/all)
- Drop files into `media/portrait`, `media/landscape`, `media/art`, or `media/display`, and/or
- Enable **Google Drive sync** (set folder IDs in config), and/or
- Enable the **Family/Friends Folder** source and set its ID.

## 6. (Optional) Birthday face boost
```bash
mkdir -p known_faces       # add known_faces/mom.jpg, dad.jpg, ...
```
Set `enable_face_recognition: true`.
> ⚠️ Face-scanning a large (e.g. 12k) library is heavy on a Pi 4. Fine to leave
> off and rely on filename keywords.

## 7. Verify
```bash
python3 verify_install.py   # fix any FAIL lines
```

## 8. First bulk Drive sync (optional)
```bash
python3 sync_now.py         # one-shot two-way mirror; can take a while
```

## 9. Run
The service is already started and auto-starts on boot. Manual run:
```bash
python3 main.py             # ESC to quit
```
On-device hotkeys: **F1** setup · **F2** senders · **F3** leaderboard · **F4** quiz.

---

### Updating later
Nothing to do — the auto-update timer pulls from GitHub every ~15 min and
restarts only when something changed. Your `display_config.json`, secrets,
contacts, favorites, and `media/` are git-ignored, so updates never touch them.

- Status: `systemctl status selah-update.timer`
- Logs: `journalctl -u selah-update.service`
- Disable: `sudo systemctl disable --now selah-update.timer`
