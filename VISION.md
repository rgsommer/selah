# Selah — Vision & Features

## What Selah Is

Selah is a fully integrated, automated home display system for the Raspberry Pi. It turns one or two screens into a living centerpiece for the home — quietly cycling family photos and videos, surfacing a verse each day, welcoming new memories by email, and marking the days that matter without anyone having to lift a finger.

The name is deliberate. Selah is the word that punctuates the Psalms — a call to pause and reflect. That's the intent: a display that invites the family to stop, look, and remember.

### Design principles

- **It just runs.** Survives missing monitors, no network, no camera, bad files, and reboots without intervention.
- **No one has to maintain it.** Photos arrive by email or Drive; birthdays celebrate themselves; the Pi updates its own code.
- **Nothing critical shown on screen.** Errors are logged and emailed, never displayed over the photos.
- **One or two screens, portrait or landscape** — the system adapts to whatever hardware is plugged in.

## Hardware

- Raspberry Pi (Pi 4 or newer recommended) running Raspberry Pi OS.
- One or two HDMI displays. With two, portrait and landscape screens run independent slideshows; with one, both orientations share it. Monitors can be added or removed while running — the system re-detects them automatically.
- Pi Camera Module (optional) — motion detection, facial recognition.
- USB microphone (optional) — voice control.
- GPIO-connected light/relay (optional) — motion-triggered night light.
- Touchscreen (optional) — swipe to navigate.

## Core Display

- Auto-rotating slideshow of photos and videos, with a configurable interval.
- Dual-screen, orientation-aware: landscape images on the landscape screen, portrait on the portrait screen; each rotates independently and is controlled by its own arrow keys (Left/Right = landscape, Up/Down = portrait).
- Random layout variety: each rotation may show one photo full-screen, a diagonal 3-photo cascade, or a 3-photo or 6-photo collage, with crossfade transitions between frames. Grids adapt to screen orientation, with a thin gutter between photos. Layout mix is tunable, and videos always play full-screen.
- Vintage effects: some photos randomly render in sepia or black & white for visual interest (tunable chance; works in single and collage views). Newly-submitted photos stay in true colour while they're being featured.
- Glance bar: an optional one-line status strip showing time · current temperature · today's forecast — e.g. `3:42 PM  14°C  Today 25°C Sunny` — at the top or bottom. The band can persist across transitions and fade in gently.
- Aspect-correct scaling with letterboxing — images are never stretched. EXIF orientation is honored so phone photos are never sideways.
- Video playback (MP4/AVI/MOV).
- On-screen metadata (optional, per item): caption, date, and file name in an unobtrusive overlay.
- Manual navigation by arrow keys or touchscreen swipe; manual moves pause auto-rotation briefly so you can linger.
- Night mode: outside waking hours the screens switch to an analog clock with a rotating nightly quote, a dimmed moon rendered at the night's real phase, and sunrise/sunset and moonrise/moonset times. Optionally, either or both HDMI outputs power down at night (DPMS/standby), and sunrise/sunset photo folders show around those events. Email intake and the night light keep working through the night, and the slideshow returns in the morning.

## Content & Scheduling

- Time zone with automatic DST — set once (e.g. America/Toronto = Eastern). Every schedule below follows it; daylight saving is handled automatically with no manual clock changes.
- Verse of the Day — pulled fresh daily with a local fallback list, shown briefly each hour.
- Daily agenda from Google Calendar — upcoming family events (across all subscribed calendars) scroll on screen, starting at a set time (e.g. 6 AM) and optionally running for a fixed duration rather than all day. A 5-day forecast panel shares the same split-screen treatment.
- Daily weather card — a clean forecast appears each morning at a configurable time (default 8 AM) and holds briefly before the slideshow resumes.
- Seasonal & liturgical themes — the display dresses itself for the calendar: Advent/Christmas, Holy Week/Resurrection Sunday, Valentine's, Thanksgiving, Reformation Day, Canada Day — subtle borders and color accents, never overwhelming the photos.

## Memories by Email

The heart of Selah: family and friends simply email photos to the display.

- **Send a photo, see it appear.** Approved senders email images/videos to the family address; they show up in the slideshow at the very next rotation, on the correctly-oriented screen. Inline photos and Apple HEIC are handled, not just attachments.
- **Captions from the subject line** — the email subject becomes the on-screen caption (the body's first sentence is a fallback).
- **Schedule by subject line** — `Happy Birthday Mom May 10` or `Anniversary 2026-06-15` queues a photo for that date; a bare date recurs every year, a full year (`Merry Christmas 2026-12-25`) shows that year only; no date means show it now.
- **Automatic, personalized replies** — every contributor gets a formatted thank-you with inline thumbnails of what they sent, plural-aware, plus gentle guidance to keep emails small (very large emails can bounce).
- **Sender approval** — new senders are held for one-tap approval, keeping the display family-safe. Bounce/mailer-daemon notices are ignored so they never become junk "photos."
- **Contributor leaderboard** — a playful tally of who's sharing the most (F3).
- **Inactivity nudges** — approved contributors who've gone quiet get a friendly, personalized reminder (with a thumbnail of one of their own past photos), throttled so no one is pestered.

### Inviting Family & Friends

Manage the family/friends list right on the device, then hit Nudge to email everyone an invitation explaining how to take part — including how to pre-send a dated birthday greeting: email a photo a few days early with a subject like `Happy Birthday, Mom Sept 4`, and it appears first thing on the morning of Sept 4, alongside everyone else's greetings for that day and favourite photos featuring that person. Adding someone to the list also lets them submit photos.

## Special-Day Automation

Selah remembers the family's important dates so no one else has to.

- A simple, family-maintained list of birthdays, anniversaries, and custom days (recurring MM-DD, or full YYYY-MM-DD to also count ages/years).
- On the morning of a match, Selah automatically celebrates: a personalized full-screen splash and toast ("Happy Birthday, Mom! — 70 today"), and it can bias the slideshow toward that person's photos for the day.
- Entirely autonomous — no one has to remember to send anything; the date is enough.

## Photo Sources

Selah blends memories from wherever the family already keeps them:

- **Email** — send a photo, see it appear.
- **Google Drive** — one or more folders, managed right on the device; two-way sync keeps the family library mirrored between the Pi and Drive automatically, downscaling very large originals to save space.
- **Phone upload** — visitors scan an on-screen QR code and upload straight from their phone over the local network (no shared folder, no account needed).
- **Local folders** — drop files straight into the on-device portrait / landscape / art / display folders.

All sources are de-duplicated (by content), oriented to the right screen, and merged into one rotation.

## Recognition & Personalization

- Facial recognition prioritization — point Selah at the people who matter (e.g., the birthday child) and their photos surface more often.
- Photo biasing by name — special days can favour a person's pictures via a filename keyword.
- Artwork support — a dedicated folder for kids' drawings and digital art, auto-oriented to the right screen.
- "On this day" flashbacks — photos from prior years resurface on their anniversary (F7 to summon them on demand).

## Smart-Home & Automation

- Motion detection (camera-based) — wake the slideshow when someone enters the room and rest it when they leave.
- Motion-triggered night light — drive a GPIO light/relay when motion is detected in the dark; auto-off on a timer, day-aware so it doesn't waste the bulb.
- Optional motion recording — capture short clips when motion is detected.
- Cloud sync & backup — two-way Google Drive sync keeps memories safe off-device and flows new cloud photos onto the display.
- Screen sleep prevention — the slideshow keeps the panels awake; night mode is the only time they intentionally blank.

## Interaction & Control

- Touchscreen — swipe to advance.
- Voice control — spoken commands ("next photo," "pause," "resume") via a USB mic.
- Web control — a password-protected page on the local network for next/previous/pause and remote photo upload, plus an unauthenticated, upload-only visitor page reached by the on-screen QR.

### On-device hotkeys

| Key | Action |
| --- | --- |
| ← / → | Previous / next photo (landscape screen) |
| ↑ / ↓ | Previous / next photo (portrait screen) |
| Space | Play / pause |
| F1 | Configuration editor (live, on-screen) |
| F2 | Sender manager (approve/remove contributors) |
| F3 | Contributor leaderboard |
| F4 | Family trivia quiz mode |
| F5 | Approve all pending senders |
| F6 | Agenda / 5-day forecast panel |
| F7 | Show today's "On this day" memories |
| F8 | Feature new photos from the last few days |
| F9 | Displays off — +1 hr per press (up to 6); nav wakes |
| F10 | Edit a photo's caption (pick it by number) |
| F11 | Show the "scan to add a photo" QR code |
| Del | Delete a photo — pick its number, then a PIN |
| H or ? | On-screen help / controls |
| Esc | Exit |

## Engagement

- Family trivia quiz (F4) — turn the photo library into a game.
- Leaderboard (F3) — friendly recognition for the most active contributors.
- Toast notifications — a gentle banner (with optional chime) when new media arrives, plus a subtle glyph beside the clock (🤗 for an emailed photo, 👀 otherwise).

## Reliability & Safety

- Never crashes on hardware changes — runs with zero, one, or two monitors, logs which display path it took, and re-detects monitors hot-plugged at runtime.
- Degrades gracefully — no camera, no mic, no network, or missing optional libraries simply disable that one feature; the slideshow keeps running.
- Errors stay off-screen — logged to disk and emailed to the owner for critical issues; viewers only ever see photos. Transient network blips don't raise false alarms.
- Self-verifying install — a built-in checker (`verify_install.py`) confirms dependencies, config, camera, mic, displays, and flags weak/plaintext secrets before you rely on it.

## On-Screen Setup (F1)

Everything is editable on the device, no keyboard-into-a-file required:

- **Layouts** — turn full-single / cascade / tile-3 / tile-6 on or off, fade transitions, and the sepia/B&W photo effects.
- **Schedule & time zone** — morning start, night stop, time zone (auto-DST), agenda start + duration, weather time, special-days time.
- **Glance bar** — time + temperature + forecast, top or bottom.
- **Photo sources** — add/remove multiple Google Drive folders (paste a share link or an ID).
- **Family & Friends** — manage the invite list and send invitations with one Nudge.
- **Night display** — which HDMI (if any) powers off at night, moon phase, verse, sunrise/sunset folders.
- Plus features (verse, face recognition, motion, night light, voice, web), captions, and notifications.

## Configuration & Security

- Secrets kept out of the main config — passwords and API keys live in an untracked local secrets file or environment variables; the on-screen editor never writes a secret back into a shared file.
- Privacy by default — the photo library, contributor list, calendar, and credentials are all device-local and excluded from the program's code repository.

## Deployment & Self-Updating

- One-line install: `curl -sSL https://www.curriculate.net/selah | bash` clones the system and runs the full installer (dependencies, camera, config templates, auto-start service).
- Auto-start on boot via systemd.
- Pull-based auto-update — the Pi checks for new code on a timer and updates itself, restarting cleanly, without ever disturbing on-device settings, secrets, or photos.

## Quick Reference

| Action | How |
| --- | --- |
| Add a photo now | Email it (no date in subject) |
| Schedule a photo / greeting | Email it — date in subject (`Happy Birthday, Mom Sept 4`) |
| Add a caption | Subject line of the email |
| Upload from a phone | Scan the on-screen QR (or press F11 to show it) |
| Feature the latest photos now | F8 |
| Edit a photo's caption | F10 |
| Delete a photo | Del (pick its number, then PIN) |
| Turn the screens off for a while | F9 (+1 hr per press; Space/arrow wakes) |
| Invite people | F1 → Family & Friends → Nudge |
| Approve a sender | F2 on the device (or F5 to approve all) |
| Edit settings | F1 on the device |
| See the leaderboard | F3 |
| Play the quiz | F4 |
| Voice command | "Selah, next photo" / "pause" / "resume" |
| Web control | `http://raspberrypi.local:5000` (upload page: `/upload`) |

## Roadmap

- Google Photos shared-album sync.
- Per-person "memory albums" auto-assembled from facial recognition.

---

*Selah runs quietly so the family doesn't have to think about it — and pauses everyone, now and then, to remember.*
