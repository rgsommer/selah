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
from random import shuffle

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
from modules.weather_display import show_weather_if_scheduled, show_status_line
from modules.voice_control import process_voice_command
from modules.theme_manager import apply_theme
from modules.quiz_mode import start_quiz_mode
from modules.web_control import start_web_server
from modules.google_drive_sync import sync_drive
from modules.special_days import check_special_days, prioritize_for_today


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


def _render_screen(screen, screen_type, files, state, config, media_log):
    """Render the next slideshow frame for one screen, with random layout variety.

    Picks a layout (single / tile3 / tile6) per rotation; videos always play
    full-screen. Advances the screen's index by the number of files consumed.
    """
    idx = state[screen_type]["index"] % len(files)
    first = files[idx]

    mode = pick_layout_mode(config)
    if first.lower().endswith(VIDEO_EXTS):
        mode = "single"  # videos never tile

    if mode == "single":
        file_date, caption = _get_media_metadata(first, media_log)
        if first.lower().endswith(VIDEO_EXTS):
            show_video(screen, first, config, file_date, caption)
        else:
            show_layout(screen, [first], config, "single", file_meta=(file_date, caption))
        state[screen_type]["index"] = (idx + 1) % len(files)
        return

    # Tile modes: gather N images (skipping videos), starting at idx.
    need = layout_file_count(mode)
    picks, i, scanned = [], idx, 0
    while len(picks) < need and scanned < len(files):
        f = files[i % len(files)]
        if not f.lower().endswith(VIDEO_EXTS):
            picks.append(f)
        i += 1
        scanned += 1

    if len(picks) < need:
        # Not enough images for a collage — fall back to a single photo.
        f = picks[0] if picks else first
        fd, cap = _get_media_metadata(f, media_log)
        show_layout(screen, [f], config, "single", file_meta=(fd, cap))
        state[screen_type]["index"] = (idx + 1) % len(files)
    else:
        show_layout(screen, picks, config, mode)
        state[screen_type]["index"] = i % len(files)


def main():
    print("[Selah] Starting display system...")
    config = load_config("display_config.json")

    # Apply timezone first so all scheduling (day/night, agenda, special days)
    # runs in the configured zone (e.g. Eastern with auto DST).
    apply_timezone(config)

    # Initialize displays
    screens = init_displays()
    if not screens:
        log_error("No displays initialized. Exiting.", critical=True, config=config)
        print("[Selah] ERROR: No displays could be initialized.")
        return

    print(f"[Selah] Initialized screens: {list(screens.keys())}")

    try:
        # Start web control server if enabled
        if config.get("web_control_enabled", False):
            start_web_server(config, screens)

        # Load media files
        portrait_files, landscape_files = get_images_and_videos(config)

        # Apply face recognition prioritization if enabled
        if config.get("enable_face_recognition", False):
            portrait_files = prioritize_images(portrait_files, config)
            landscape_files = prioritize_images(landscape_files, config)

        shuffle(portrait_files)
        shuffle(landscape_files)

        # Bias toward the birthday/anniversary person's photos if today is theirs.
        portrait_files = prioritize_for_today(portrait_files, config)
        landscape_files = prioritize_for_today(landscape_files, config)

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

        rotate_interval = config.get("rotate_interval", 10)
        motion_timeout = config.get("motion_timeout", 300)
        last_email_check = 0
        last_media_refresh = 0
        last_drive_sync = 0
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

            # Handle keyboard/touch events (also processes ESC to exit)
            try:
                state = handle_events(screens, config, portrait_files, landscape_files, state)
            except SystemExit:
                print("[Selah] Shutting down...")
                break

            # Handle F-key events separately (handle_events consumes events,
            # so we check for F-keys that weren't consumed)
            for event in pygame.event.get():
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

            # ---- NIGHT MODE ----
            if is_display_off(current_time, config):
                # Night light: detect motion in the dark even though the
                # slideshow is off — this is exactly when the light is wanted.
                if config.get("night_light_enabled", False) and config.get("motion_detection_enabled", False):
                    try:
                        detect_motion(config, screens)
                    except Exception as e:
                        log_error(f"Night-mode motion check failed: {e}")
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
                last_email_check = current_ts

            # ---- GOOGLE DRIVE SYNC (throttled) ----
            if config.get("cloud_backup_enabled", False) and current_ts - last_drive_sync > drive_sync_interval:
                try:
                    downloaded, uploaded = sync_drive(config, screens)
                    if downloaded:
                        show_toast_if_needed(screens, config, f"Synced {downloaded} new photo(s) from Google Drive")
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
                        shuffle(portrait_files)
                        portrait_files = prioritize_for_today(portrait_files, config)
                        if current_p and current_p in portrait_files:
                            state["portrait"]["index"] = portrait_files.index(current_p)
                        else:
                            state["portrait"]["index"] = 0
                    if new_landscape:
                        current_l = landscape_files[state["landscape"]["index"]] if landscape_files and state["landscape"]["index"] < len(landscape_files) else None
                        landscape_files = new_landscape
                        shuffle(landscape_files)
                        landscape_files = prioritize_for_today(landscape_files, config)
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
            if state.get("slideshow_active", True) or not config.get("motion_triggered_slideshow", False):
                is_single_screen = len([k for k in screens if k in ("portrait", "landscape")]) == 1

                for screen_type, screen in screens.items():
                    if screen_type not in ("portrait", "landscape"):
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
                        files = landscape_files if screen_type == "landscape" else portrait_files

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
