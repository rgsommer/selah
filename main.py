#!/usr/bin/env python3
"""Selah Display System - Main entry point.

A fully integrated home display system for family photos, messages,
verses, quotes, calendar events, and celebrations across dual HDMI screens.
"""

import datetime
import time
import json
import sys
import os
from random import shuffle, randrange

# Ensure we're running from the script's directory
os.chdir(os.path.dirname(os.path.abspath(__file__)))

import pygame

from modules.config_utils import load_config, save_config
from modules.display_handler import (
    init_displays, show_image, show_video, check_for_display_changes,
    show_layout, pick_layout_mode, layout_file_count,
)
from modules.image_loader import get_images_and_videos
from modules.event_handler import handle_events
from modules.time_manager import is_display_off, apply_timezone
from modules.email_handler import check_for_new_emails, send_annual_invites
from modules.logger import log_error
from modules.toast import show_toast_if_needed
from modules.verse_handler import show_verse_if_scheduled
from modules.calendar_display import show_calendar_if_scheduled
from modules.motion_detector import detect_motion
from modules.face_recognition_handler import prioritize_images
from modules.quote_loader import show_clock_with_quote
from modules.moon_phase import show_moon_phase
from modules.selah_config_gui import show_config_gui
from modules.sender_manager import show_sender_manager
from modules.leaderboard import show_leaderboard
from modules.weather_display import show_weather_if_scheduled, show_status_line, show_weather_pill
from modules.voice_control import process_voice_command
from modules.theme_manager import apply_theme
from modules.quiz_mode import start_quiz_mode
from modules.web_control import start_web_server
from modules.google_drive_sync import sync_drive
from modules.special_days import check_special_days, prioritize_for_today
from modules.on_this_day import todays_flashbacks
from modules.upload_qr import show_upload_qr_if_scheduled
from modules.now_showing import set_current as _set_now_showing
from modules.favorites import prioritize_favorites
from modules.coming_up import show_coming_up_if_scheduled
from modules.pending_badge import show_pending_badge


def _load_media_log():
    """Load the media log for metadata lookups."""
    try:
        with open("media_log.json", "r") as f:
            return json.load(f)
    except Exception:
        return []


def _get_media_metadata(file_path, media_log):
    """Look up date and caption for a file from the media log."""
    entry = next((e for e in media_log if e.get("file_path") == file_path), None)
    if entry:
        return entry.get("date"), entry.get("caption")
    return None, None


VIDEO_EXTS = ('.mp4', '.avi', '.mov')


def _display_file(screen, file_path, config, file_date=None, caption=None):
    """Display a single file (image or video) on a screen."""
    if file_path.lower().endswith(VIDEO_EXTS):
        show_video(screen, file_path, config, file_date, caption)
    else:
        show_image(screen, file_path, config, file_date, caption)


def _recent_store(state):
    """Shared 'recently shown' memory (set for lookup + deque for ordering)."""
    r = state.get("_recent")
    if r is None:
        from collections import deque
        r = {"set": set(), "order": deque()}
        state["_recent"] = r
    return r


def _recent_cap(config, total):
    """How many recent photos to remember before one may repeat."""
    cap = int(config.get("recent_memory", 0) or 0)
    if cap > 0:
        return cap
    # Auto: ~40% of the library, bounded so it stays cheap.
    return min(500, max(20, int(total * 0.4)))


def _is_recent(state, path):
    return path in _recent_store(state)["set"]


def _mark_shown(state, paths, config, total):
    r = _recent_store(state)
    cap = _recent_cap(config, total)
    for p in paths:
        if p not in r["set"]:
            r["set"].add(p)
            r["order"].append(p)
    while len(r["order"]) > cap:
        r["set"].discard(r["order"].popleft())


def _health_check(config):
    """Email the owner if disk space runs low (logger emails critical errors)."""
    import shutil
    try:
        total, _used, free = shutil.disk_usage(config.get("media_folder", "."))
        pct_free = free * 100 // max(1, total)
        if pct_free < int(config.get("disk_warn_percent", 10)):
            log_error(f"Low disk space: {pct_free}% free on the Selah Pi", critical=True, config=config)
    except Exception as e:
        log_error(f"Health check failed: {e}")


def _check_flashbacks(state, config, portrait_files, landscape_files, screens):
    """Once each morning, queue today's scheduled greetings and on-this-day photos."""
    today = datetime.date.today().isoformat()
    if state.get("flashback_date") == today:
        return
    if datetime.datetime.now().strftime("%H:%M") < config.get("on_time", "06:00"):
        return
    state["flashback_date"] = today

    from collections import deque
    queue = []

    # Dated greetings scheduled for today (family folder / email).
    try:
        from modules.scheduled_media import todays_scheduled
        for it in todays_scheduled():
            queue.append((it["path"], it.get("caption") or "A special greeting"))
    except Exception as e:
        log_error(f"Scheduled media check failed: {e}")

    # On-this-day flashbacks (photos from prior years).
    if config.get("on_this_day_enabled", True):
        files = list(dict.fromkeys(portrait_files + landscape_files))
        try:
            fb = todays_flashbacks(files, config)
        except Exception as e:
            log_error(f"Flashback scan failed: {e}")
            fb = []
        # Shuffle so the flashback order varies year to year (and a random 20
        # are chosen when more than 20 photos qualify for today).
        shuffle(fb)
        for path, year in fb[:20]:
            queue.append((path, f"On this day, {year}"))

    if not queue:
        return
    state["flashback_queue"] = deque(queue)
    show_toast_if_needed(screens, config, "Today's special photos")


def _render_frame(screen, frame, config, media_log):
    """Render an already-decided frame: {"mode", "picks", "caption"}."""
    try:
        mode, picks = frame["mode"], frame["picks"]
        cap_override = frame.get("caption")
        if mode == "single":
            f = picks[0]
            if f.lower().endswith(VIDEO_EXTS):
                fd, cap = _get_media_metadata(f, media_log)
                show_video(screen, f, config, fd, cap)
            else:
                fd, cap = ((None, cap_override) if cap_override is not None
                           else _get_media_metadata(f, media_log))
                show_layout(screen, [f], config, "single", file_meta=(fd, cap))
            _set_now_showing(f)
        else:
            show_layout(screen, picks, config, mode)
            _set_now_showing(picks[0])
    except Exception as e:
        log_error(f"Render frame failed: {e}")


def _push_history(state, screen_type, frame):
    """Record a rendered frame so the arrows can browse back/forward through it."""
    sd = state.setdefault(screen_type, {"index": 0, "paused_until": 0})
    hist = sd.setdefault("history", [])
    hist.append(frame)
    if len(hist) > 40:
        del hist[0]
    sd["hist_pos"] = len(hist) - 1


def _nav_history(screen, screen_type, files, state, config, media_log, direction):
    """Manual browse: replay the previous/next full render, or make a new one."""
    sd = state.get(screen_type)
    if sd is None or not files:
        return
    hist = sd.get("history", [])
    pos = sd.get("hist_pos", len(hist) - 1)
    if direction < 0:
        if pos > 0:
            sd["hist_pos"] = pos - 1
            _render_frame(screen, hist[pos - 1], config, media_log)
    else:
        if pos < len(hist) - 1:
            sd["hist_pos"] = pos + 1
            _render_frame(screen, hist[pos + 1], config, media_log)
        else:
            _render_screen(screen, screen_type, files, state, config, media_log)


def _render_screen(screen, screen_type, files, state, config, media_log):
    """Render the next slideshow frame for one screen, with random layout variety,
    recording it so the arrows can browse back/forward through full renders.

    Videos always play full-screen; recently-shown photos are skipped.
    """
    # Morning queue (scheduled greetings + on-this-day) plays first, one/frame.
    fbq = state.get("flashback_queue")
    if fbq:
        path, caption = fbq.popleft()
        if os.path.exists(path) and not path.lower().endswith(VIDEO_EXTS):
            frame = {"mode": "single", "picks": [path], "caption": caption}
            _push_history(state, screen_type, frame)
            _render_frame(screen, frame, config, media_log)
            _mark_shown(state, [path], config, len(files))
            return

    idx = state[screen_type]["index"] % len(files)

    # Skip ahead past recently-shown photos (bounded so we always make progress).
    if config.get("recent_memory_enabled", True):
        scanned = 0
        while _is_recent(state, files[idx]) and scanned < len(files):
            idx = (idx + 1) % len(files)
            scanned += 1
    first = files[idx]

    mode = pick_layout_mode(config)
    if first.lower().endswith(VIDEO_EXTS):
        mode = "single"  # videos never tile

    if mode == "single":
        frame = {"mode": "single", "picks": [first], "caption": None}
        _push_history(state, screen_type, frame)
        _render_frame(screen, frame, config, media_log)
        _mark_shown(state, [first], config, len(files))
        state[screen_type]["index"] = (idx + 1) % len(files)
        return

    # Tile/split modes: gather N images (skipping videos and recently-shown).
    need = layout_file_count(mode)
    skip_recent = config.get("recent_memory_enabled", True)
    picks, i, scanned = [], idx, 0
    while len(picks) < need and scanned < len(files):
        f = files[i % len(files)]
        if not f.lower().endswith(VIDEO_EXTS) and not (skip_recent and _is_recent(state, f)):
            picks.append(f)
        i += 1
        scanned += 1
    if len(picks) < need:  # recency filtering starved us — allow recent images
        picks, i, scanned = [], idx, 0
        while len(picks) < need and scanned < len(files):
            f = files[i % len(files)]
            if not f.lower().endswith(VIDEO_EXTS):
                picks.append(f)
            i += 1
            scanned += 1

    if len(picks) < need:
        f = picks[0] if picks else first
        frame = {"mode": "single", "picks": [f], "caption": None}
        _push_history(state, screen_type, frame)
        _render_frame(screen, frame, config, media_log)
        _mark_shown(state, [f], config, len(files))
        state[screen_type]["index"] = (idx + 1) % len(files)
    else:
        frame = {"mode": mode, "picks": picks, "caption": None}
        _push_history(state, screen_type, frame)
        _render_frame(screen, frame, config, media_log)
        _mark_shown(state, picks, config, len(files))
        state[screen_type]["index"] = i % len(files)


def main():
    print("[Selah] Starting display system...")
    config = load_config("display_config.json")

    # Apply timezone first so all scheduling (day/night, agenda, special days)
    # runs in the configured zone (e.g. Eastern with auto DST).
    apply_timezone(config)

    # Initialize displays
    screens = init_displays(config)
    if not screens:
        log_error("No displays initialized. Exiting.", critical=True, config=config)
        print("[Selah] ERROR: No displays could be initialized.")
        return

    print(f"[Selah] Initialized screens: {list(screens.keys())}")

    try:
        # Start web control server if enabled
        if config.get("web_control_enabled", False):
            start_web_server(config, screens)

        # Ensure each contact has their own upload subfolder in the family folder.
        if config.get("family_folder_enabled", False):
            try:
                from modules.google_drive_sync import ensure_family_subfolders
                ensure_family_subfolders(config)
            except Exception as e:
                log_error(f"Family subfolder setup failed: {e}")

        # Load media files
        portrait_files, landscape_files = get_images_and_videos(config)

        # Apply face recognition prioritization if enabled
        if config.get("enable_face_recognition", False):
            portrait_files = prioritize_images(portrait_files, config)
            landscape_files = prioritize_images(landscape_files, config)

        # Keep image_loader's folder-balanced order (each subfolder gets equal
        # airtime) unless the user wants a purely-random shuffle instead.
        if not config.get("balanced_rotation", True):
            shuffle(portrait_files)
            shuffle(landscape_files)

        # Bias toward the birthday/anniversary person's photos if today is theirs.
        portrait_files = prioritize_for_today(portrait_files, config)
        landscape_files = prioritize_for_today(landscape_files, config)
        # Favorited photos appear more often.
        portrait_files = prioritize_favorites(portrait_files, config)
        landscape_files = prioritize_favorites(landscape_files, config)

        print(f"[Selah] Found {len(portrait_files)} portrait and {len(landscape_files)} landscape files")

        if not portrait_files and not landscape_files:
            log_error("No media files found. Will keep checking...", config=config)
            # Don't exit - keep running so email intake can still work

        # Initialize state for each screen type
        state = {
            "portrait": {"index": 0, "paused_until": 0},
            "landscape": {"index": 0, "paused_until": 0},
            "slideshow_active": True,
            "last_motion": time.time(),
            "new_media": None,
        }
        # Cover extra same-orientation screens (e.g. 'landscape_2') so they get
        # their own rotation index instead of being skipped.
        for _sk in screens:
            state.setdefault(_sk, {"index": 0, "paused_until": 0})

        # Start each screen at a random spot so the same photos don't open every
        # launch (each screen also gets a different starting point).
        for _sk, _sv in state.items():
            if isinstance(_sv, dict) and "index" in _sv:
                _n = len(portrait_files) if _sk.startswith("portrait") else len(landscape_files)
                if _n > 1:
                    _sv["index"] = randrange(_n)

        rotate_interval = config.get("rotate_interval", 10)
        motion_timeout = config.get("motion_timeout", 300)
        last_email_check = 0
        last_media_refresh = 0
        last_drive_sync = 0
        last_health_check = 0
        health_check_interval = 3600  # disk check hourly
        email_check_interval = 60  # Check email every 60 seconds
        media_refresh_interval = 120  # Refresh file list every 2 minutes
        drive_sync_interval = config.get("drive_sync_interval", 300)

        media_log = _load_media_log()

        print("[Selah] Entering main display loop...")

        while True:
            now = datetime.datetime.now()
            current_time = now.time()
            current_ts = time.time()

            # ---- HOT-PLUG MONITOR RE-DETECTION ----
            screens = check_for_display_changes(screens, config)

            # Apply theme (checks internally, runs max once per minute)
            if config.get("theme_enabled", False):
                apply_theme(screens, config)

            # Special-day automation (birthdays/anniversaries/custom days).
            # Self-throttles to one scan/minute and one celebration/day.
            if config.get("special_days_enabled", False):
                check_special_days(screens, config, state)

            # On-this-day flashbacks — queue once each morning.
            _check_flashbacks(state, config, portrait_files, landscape_files, screens)

            # Drain the event queue ONCE, then share it with both handlers so
            # neither starves the other (this is why F-keys never fired before).
            events = pygame.event.get()
            try:
                state = handle_events(screens, config, portrait_files, landscape_files, state, events)
            except SystemExit:
                print("[Selah] Shutting down...")
                break

            # F-key actions (live in main.py because they call its UIs).
            for event in events:
                if event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_ESCAPE:
                        print("[Selah] ESC pressed - shutting down.")
                        pygame.quit()
                        return
                    elif event.key == pygame.K_F1:
                        target = screens.get("landscape") or screens.get("portrait")
                        show_config_gui(target, config)
                        save_config(config, "display_config.json")
                        # Reload settings that may have changed
                        rotate_interval = config.get("rotate_interval", 10)
                        motion_timeout = config.get("motion_timeout", 300)
                    elif event.key == pygame.K_F2:
                        target = screens.get("landscape") or screens.get("portrait")
                        show_sender_manager(target, config)
                    elif event.key == pygame.K_F3:
                        show_leaderboard(screens, config)
                    elif event.key == pygame.K_F4:
                        start_quiz_mode(screens, config, portrait_files + landscape_files)
                    elif event.key == pygame.K_F5:
                        # Approve every pending sender at once.
                        try:
                            from modules.email_handler import approve_all_pending
                            n = approve_all_pending(config)
                            if n:
                                show_toast_if_needed(screens, config,
                                                     f"Approved {n} pending sender(s)")
                        except Exception as e:
                            log_error(f"Approve-all failed: {e}")
                    elif event.key == pygame.K_SPACE:
                        # Play / pause the slideshow.
                        state["paused"] = not state.get("paused", False)
                        show_toast_if_needed(screens, config,
                                             "Paused" if state["paused"] else "Playing")
                    elif event.key in (pygame.K_LEFT, pygame.K_UP):
                        state["nav_request"] = -1   # previous render, both screens
                    elif event.key in (pygame.K_RIGHT, pygame.K_DOWN):
                        state["nav_request"] = 1    # next render, both screens

            # ---- MANUAL BROWSE (arrows / swipe) — step full renders on every screen ----
            _dir = state.pop("nav_request", 0)
            if _dir:
                pause_for = config.get("manual_navigation_pause", 60)
                for _stype, _screen in screens.items():
                    if _stype.startswith("portrait") or _stype.startswith("landscape"):
                        _files = portrait_files if _stype.startswith("portrait") else landscape_files
                        _nav_history(_screen, _stype, _files, state, config, media_log, _dir)
                        state.setdefault(_stype, {})["paused_until"] = current_ts + pause_for

            # ---- NIGHT MODE ----
            if is_display_off(current_time, config):
                # Night light: detect motion in the dark even though the
                # slideshow is off — this is exactly when the light is wanted.
                if config.get("night_light_enabled", False) and config.get("motion_detection_enabled", False):
                    try:
                        detect_motion(config, screens)
                    except Exception as e:
                        log_error(f"Night-mode motion check failed: {e}")

                if config.get("night_screen_off", False):
                    # True dark: actually power off the HDMI (no backlight glow).
                    from modules.screen_power import screen_off
                    screen_off()
                else:
                    # Dedicate one HDMI to a large moon phase (if enabled); the
                    # rest show the analog clock + nightly quote.
                    for i, screen in enumerate(screens.values()):
                        if config.get("moon_phase_enabled", True) and i == 0:
                            show_moon_phase(screen, config)
                        else:
                            show_clock_with_quote(screen, config)
                time.sleep(10)
                # Still check email during night mode
                if current_ts - last_email_check > email_check_interval:
                    check_for_new_emails(config, screens)
                    last_email_check = current_ts
                continue

            # Daytime: if night mode blanked the HDMI, power it back on.
            if config.get("night_screen_off", False):
                from modules.screen_power import screen_on
                screen_on()

            # ---- MOTION DETECTION ----
            if config.get("motion_triggered_slideshow", False):
                if config.get("motion_detection_enabled", False):
                    if detect_motion(config, screens):
                        state["slideshow_active"] = True
                        state["last_motion"] = current_ts
                    elif current_ts - state["last_motion"] > motion_timeout:
                        state["slideshow_active"] = False
                        for screen in screens.values():
                            screen.fill((0, 0, 0))
                        try:
                            pygame.display.flip()
                        except Exception:
                            pass
                        time.sleep(5)
                        continue

            # ---- EMAIL CHECK (throttled) ----
            if current_ts - last_email_check > email_check_interval:
                check_for_new_emails(config, screens)
                # Check if annual invites need to go out (first week of January)
                try:
                    send_annual_invites(config)
                except Exception as e:
                    log_error(f"Annual invite check failed: {e}")
                # Weekly digest email (self-throttles to once per week).
                if config.get("weekly_digest_enabled", False):
                    try:
                        from modules.email_handler import send_weekly_digest
                        send_weekly_digest(config)
                    except Exception as e:
                        log_error(f"Weekly digest check failed: {e}")
                last_email_check = current_ts

            # ---- HEALTH WATCHDOG (disk space, throttled) ----
            if config.get("health_watchdog_enabled", False) and current_ts - last_health_check > health_check_interval:
                _health_check(config)
                last_health_check = current_ts

            # ---- GOOGLE DRIVE SYNC (throttled) ----
            if config.get("cloud_backup_enabled", False) and current_ts - last_drive_sync > drive_sync_interval:
                try:
                    downloaded, uploaded = sync_drive(config, screens)
                    if downloaded:
                        # No toast for Drive syncs — only approved-sender email
                        # submissions pop a "New photo" toast.
                        print(f"[Selah] Drive sync: {downloaded} new photo(s)")
                except Exception as e:
                    log_error(f"Drive sync failed: {e}", config=config)
                last_drive_sync = current_ts

            # ---- PERIODIC MEDIA REFRESH ----
            if current_ts - last_media_refresh > media_refresh_interval:
                new_portrait, new_landscape = get_images_and_videos(config)
                if new_portrait or new_landscape:
                    if config.get("enable_face_recognition", False):
                        new_portrait = prioritize_images(new_portrait, config)
                        new_landscape = prioritize_images(new_landscape, config)
                    # Only update if we got files
                    if new_portrait:
                        # Preserve current position if possible
                        current_p = portrait_files[state["portrait"]["index"]] if portrait_files and state["portrait"]["index"] < len(portrait_files) else None
                        portrait_files = new_portrait
                        if not config.get("balanced_rotation", True):
                            shuffle(portrait_files)
                        portrait_files = prioritize_for_today(portrait_files, config)
                        portrait_files = prioritize_favorites(portrait_files, config)
                        if current_p and current_p in portrait_files:
                            state["portrait"]["index"] = portrait_files.index(current_p)
                        else:
                            state["portrait"]["index"] = 0
                    if new_landscape:
                        current_l = landscape_files[state["landscape"]["index"]] if landscape_files and state["landscape"]["index"] < len(landscape_files) else None
                        landscape_files = new_landscape
                        if not config.get("balanced_rotation", True):
                            shuffle(landscape_files)
                        landscape_files = prioritize_for_today(landscape_files, config)
                        landscape_files = prioritize_favorites(landscape_files, config)
                        if current_l and current_l in landscape_files:
                            state["landscape"]["index"] = landscape_files.index(current_l)
                        else:
                            state["landscape"]["index"] = 0
                    media_log = _load_media_log()
                last_media_refresh = current_ts

            # ---- IMMEDIATE DISPLAY of new media ----
            if state.get("new_media") and config.get("immediate_display", False):
                for screen_type, screen in screens.items():
                    if screen_type in (state.get("new_media") or {}):
                        file_path = state["new_media"][screen_type]
                        file_date, caption = _get_media_metadata(file_path, media_log)
                        _display_file(screen, file_path, config, file_date, caption)
                        state[screen_type]["paused_until"] = current_ts + config.get("manual_navigation_pause", 60)
                state["new_media"] = None
                continue

            # ---- TOAST NOTIFICATIONS ----
            show_toast_if_needed(screens, config)

            # ---- SCHEDULED OVERLAYS ----
            if config.get("verse_display_enabled", False):
                show_verse_if_scheduled(screens, config)

            if config.get("calendar_display_enabled", False):
                show_calendar_if_scheduled(screens, config)

            if config.get("weather_enabled", False):
                show_weather_if_scheduled(screens, config)

            # ---- VOICE CONTROL ----
            if config.get("voice_control_enabled", False):
                process_voice_command(screens, config, state, portrait_files, landscape_files)

            # ---- MAIN SLIDESHOW ROTATION ----
            if not state.get("paused", False) and (
                    state.get("slideshow_active", True) or not config.get("motion_triggered_slideshow", False)):
                photo_screens = [k for k in screens
                                 if k.startswith("portrait") or k.startswith("landscape")]
                is_single_screen = len(photo_screens) == 1

                for screen_type, screen in screens.items():
                    # Handle every photo screen, including 'landscape_2'/'portrait_2'.
                    if not (screen_type.startswith("portrait") or screen_type.startswith("landscape")):
                        continue
                    # Skip if manually paused
                    if current_ts < state.get(screen_type, {}).get("paused_until", 0):
                        continue

                    if is_single_screen:
                        # Single screen: combine both lists so all photos get shown
                        combined = portrait_files + landscape_files
                        # Remove duplicates (videos appear in both lists)
                        combined = list(dict.fromkeys(combined))
                        files = combined
                    else:
                        files = portrait_files if screen_type.startswith("portrait") else landscape_files

                    if not files:
                        # Show a "no media" placeholder
                        screen.fill((20, 20, 40))
                        try:
                            font = pygame.font.Font(None, 36)
                            text = font.render("Selah - Waiting for photos...", True, (150, 150, 150))
                            rect = text.get_rect(center=screen.get_rect().center)
                            screen.blit(text, rect)
                            pygame.display.flip()
                        except Exception:
                            pass
                        continue

                    _render_screen(screen, screen_type, files, state, config, media_log)

            # ---- STATUS LINE (time + temp + today's forecast) ----
            # Drawn last so it sits on top of the freshly rendered photo.
            if config.get("status_line_enabled", False):
                show_status_line(screens, config)

            # ---- WEATHER PILL (always-on corner) ----
            if config.get("weather_pill_enabled", False):
                show_weather_pill(screens, config)

            # ---- PHONE-UPLOAD QR (periodic corner overlay) ----
            if config.get("upload_qr_enabled", False):
                show_upload_qr_if_scheduled(screens, config)

            # ---- "COMING UP" birthday heads-up (periodic) ----
            if config.get("coming_up_enabled", False):
                show_coming_up_if_scheduled(screens, config)

            # ---- PENDING-APPROVAL badge (subtle corner chip; F5 approves all) ----
            show_pending_badge(screens, config)

            time.sleep(rotate_interval)

    except KeyboardInterrupt:
        print("\n[Selah] Interrupted - shutting down.")
    except Exception as e:
        log_error(f"Main loop failed: {e}", critical=True, config=config)
        print(f"[Selah] FATAL ERROR: {e}")
        import traceback
        traceback.print_exc()
    finally:
        # Cleanup
        try:
            from modules.motion_detector import cleanup
            cleanup()
        except Exception:
            pass
        try:
            pygame.quit()
        except Exception:
            pass
        print("[Selah] Display system stopped.")


if __name__ == "__main__":
    main()
