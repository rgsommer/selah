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
from modules.email_handler import check_for_new_emails, send_annual_invites, send_inactivity_nudges
from modules.logger import log_error
from modules.toast import show_toast_if_needed
from modules.verse_handler import show_verse_if_scheduled
from modules.calendar_display import (
    show_calendar_if_scheduled, agenda_in_window, render_agenda_panel,
)
from modules.motion_detector import detect_motion
from modules.face_recognition_handler import prioritize_images
from modules.quote_loader import show_clock_with_quote
from modules.moon_phase import show_moon_phase
from modules.selah_config_gui import show_config_gui
from modules.sender_manager import show_sender_manager
from modules.leaderboard import show_leaderboard
from modules.weather_display import (
    show_weather_if_scheduled, show_status_line, show_weather_pill,
    draw_status_line, draw_weather_pill, tick_forecast, render_forecast_panel,
)
from modules.voice_control import process_voice_command
from modules.theme_manager import apply_theme
from modules.quiz_mode import start_quiz_mode
from modules.web_control import start_web_server
from modules.google_drive_sync import start_background_sync, take_sync_result, is_syncing
from modules.special_days import check_special_days, prioritize_for_today
from modules.on_this_day import todays_flashbacks
from modules.upload_qr import show_upload_qr_if_scheduled
from modules.now_showing import set_current as _set_now_showing, get_current as _get_now_showing
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


RECENT_FILE = "recent_shown.json"


def _recent_store(state):
    """Shared 'recently shown' memory (set for lookup + deque for ordering),
    loaded from disk on first use so it survives restarts."""
    r = state.get("_recent")
    if r is None:
        from collections import deque
        order = []
        try:
            with open(RECENT_FILE) as f:
                order = [p for p in json.load(f) if isinstance(p, str)]
        except Exception:
            order = []
        r = {"set": set(order), "order": deque(order), "last_save": 0.0}
        state["_recent"] = r
    return r


def _save_recent(state):
    """Persist the recently-shown list (best-effort)."""
    r = state.get("_recent")
    if not r:
        return
    try:
        with open(RECENT_FILE, "w") as f:
            json.dump(list(r["order"]), f)
        r["last_save"] = time.time()
    except Exception as e:
        log_error(f"Failed to save recent-shown list: {e}")


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
    changed = False
    for p in paths:
        if p not in r["set"]:
            r["set"].add(p)
            r["order"].append(p)
            changed = True
    while len(r["order"]) > cap:
        r["set"].discard(r["order"].popleft())
        changed = True
    # Throttle disk writes to once every 30s.
    if changed and time.time() - r.get("last_save", 0) > 30:
        _save_recent(state)


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
    greetings = []   # time-sensitive — always shown first thing
    memories = []    # on-this-day flashbacks — first thing OR sprinkled

    # Dated greetings scheduled for today (family folder / email).
    try:
        from modules.scheduled_media import todays_scheduled
        for it in todays_scheduled():
            greetings.append((it["path"], it.get("caption") or "A special greeting"))
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
            memories.append((path, f"On this day, {year}"))

    # Mark this hour as already-queued so the hourly re-queue doesn't double up.
    state["last_greeting_hour"] = datetime.datetime.now().strftime("%Y-%m-%d %H")

    if not greetings and not memories:
        return

    if config.get("on_this_day_sprinkle", False) and memories:
        # Greetings still play first thing; memories release one at a time
        # through the day so a flashback surfaces every so often.
        state["flashback_queue"] = deque(greetings)
        state["sprinkle_pool"] = deque(memories)
        state["next_sprinkle"] = time.time() + config.get(
            "on_this_day_interval_minutes", 30) * 60
        show_toast_if_needed(screens, config, "Today's memories will surface through the day")
    else:
        state["flashback_queue"] = deque(greetings + memories)
        show_toast_if_needed(screens, config, "Today's special photos")


def _maybe_hourly_greetings(state, config):
    """Re-queue today's dated greetings at the top of each hour, so they recur
    through the day (in turn with the rotation), not just first thing."""
    if not config.get("greetings_hourly", True):
        return
    hour_key = datetime.datetime.now().strftime("%Y-%m-%d %H")
    if state.get("last_greeting_hour") == hour_key:
        return
    state["last_greeting_hour"] = hour_key
    try:
        from modules.scheduled_media import todays_scheduled
        items = todays_scheduled()
    except Exception:
        return
    if not items:
        return
    from collections import deque
    fq = state.get("flashback_queue")
    if not isinstance(fq, deque):
        fq = deque()
        state["flashback_queue"] = fq
    for it in items:
        fq.append((it["path"], it.get("caption") or "A special greeting"))


def _maybe_feature_recent(state, config):
    """Feature newly-submitted (non-special) photos for feature_new_days days:
    re-queue the last N days of submissions each hour so they show regularly
    before folding into the normal rotation. Excludes dated greetings."""
    if not config.get("feature_new_enabled", True):
        return
    days = int(config.get("feature_new_days", 3) or 0)
    if days <= 0:
        return
    hour_key = datetime.datetime.now().strftime("%Y-%m-%d %H")
    if state.get("last_feature_hour") == hour_key:
        return
    state["last_feature_hour"] = hour_key
    try:
        with open("media_log.json") as f:
            log = json.load(f)
    except Exception:
        return
    try:
        from modules.scheduled_media import scheduled_paths
        sched = scheduled_paths()
    except Exception:
        sched = set()
    cutoff = datetime.datetime.now() - datetime.timedelta(days=days)
    from collections import deque
    fq = state.get("flashback_queue")
    if not isinstance(fq, deque):
        fq = deque()
        state["flashback_queue"] = fq
    added = 0
    for e in reversed(log):                     # newest first, capped
        if added >= 20:
            break
        p = e.get("file_path")
        ts = e.get("timestamp")
        if not p or not ts or p in sched or not os.path.exists(p):
            continue
        try:
            if datetime.datetime.fromisoformat(ts) < cutoff:
                continue
        except Exception:
            continue
        fq.append((p, e.get("caption") or ""))
        added += 1


def _recent_media_items(config, days):
    """All photos submitted in the last `days` days, newest first, as
    (path, caption) — used by F8 to feature the latest arrivals on demand."""
    try:
        with open("media_log.json") as f:
            log = json.load(f)
    except Exception:
        return []
    cutoff = datetime.datetime.now() - datetime.timedelta(days=max(1, days))
    seen, items = set(), []
    for e in reversed(log):                         # newest first
        p, ts = e.get("file_path"), e.get("timestamp")
        if not p or not ts or p in seen or not os.path.exists(p):
            continue
        if p.lower().endswith(VIDEO_EXTS):
            continue
        try:
            if datetime.datetime.fromisoformat(ts) < cutoff:
                continue
        except Exception:
            continue
        seen.add(p)
        items.append((p, e.get("caption") or ""))
    return items


def _queue_feature_by_orientation(items, screens, portrait_files, landscape_files,
                                  state, opposite=False, front=False):
    """Route F8's recent photos into per-screen queues, matched by orientation so
    portraits show on the portrait screen and landscapes on the landscape screen,
    each photo on exactly one screen (no cross-screen duplicates). With
    opposite=True the pairing is flipped (portraits -> landscape screen). Returns
    the number of photos queued."""
    from collections import deque
    photo_types = [t for t in screens if t.startswith(("portrait", "landscape"))]
    if not photo_types:
        return 0
    # Classify each SCREEN by its ACTUAL surface dimensions, not its name — a
    # software-rotated portrait screen has a tall (h>w) surface. This is the
    # robust source of truth; names can be misleading.
    p_types, l_types = [], []
    for t in photo_types:
        try:
            w, h = screens[t].get_size()
        except Exception:
            w, h = 1, 1
        (p_types if h > w else l_types).append(t)
    # Which screen a portrait vs a landscape photo should target.
    port_target = l_types if opposite else p_types
    land_target = p_types if opposite else l_types
    pset, lset = set(portrait_files), set(landscape_files)

    def _is_port(path):
        if path in pset:
            return True
        if path in lset:
            return False
        try:
            from modules.image_loader import is_portrait
            return is_portrait(path)
        except Exception:
            return False

    buckets = {t: [] for t in photo_types}
    nport = nland = 0
    for path, caption in items:                       # newest first
        if _is_port(path):
            nport += 1
            targets = port_target or photo_types
        else:
            nland += 1
            targets = land_target or photo_types
        t = min(targets, key=lambda x: len(buckets[x]))   # balance same-orient screens
        buckets[t].append((path, caption))

    fbs = state.setdefault("feature_by_screen", {})
    total = 0
    for t, lst in buckets.items():
        if not lst:
            continue
        dq = fbs.get(t)
        if not isinstance(dq, deque):
            dq = deque()
            fbs[t] = dq
        if front:                       # new arrivals jump to the next rotation
            for it in reversed(lst):
                dq.appendleft(it)
        else:                           # F8 batch appends after any current queue
            dq.extend(lst)
        total += len(lst)
    log_error(f"[feature] {'arrival' if front else 'F8'} opposite={opposite}; "
              f"portrait->{port_target}, landscape->{land_target}; "
              f"{nport}p/{nland}l; queued " + ", ".join(f"{t}:{len(b)}" for t, b in buckets.items()))
    return total


def _draw_blackout_preview(screens, hours):
    """Show the accumulating F9 blackout stack on the (still-on) screens."""
    for stype, screen in screens.items():
        if not stype.startswith(("portrait", "landscape")):
            continue
        try:
            w, h = screen.get_size()
            big = pygame.font.Font(None, max(48, w // 16))
            small = pygame.font.Font(None, max(24, w // 42))
            l1 = big.render(f"Displays off: {hours} hour{'s' if hours != 1 else ''}",
                            True, (255, 214, 10))
            l2 = small.render("F9 = +1 hour   ·   Space / arrow = cancel",
                              True, (225, 225, 225))
            pw = max(l1.get_width(), l2.get_width()) + 60
            ph = l1.get_height() + l2.get_height() + 48
            panel = pygame.Surface((pw, ph), pygame.SRCALPHA)
            panel.fill((0, 0, 0, 205))
            panel.blit(l1, ((pw - l1.get_width()) // 2, 18))
            panel.blit(l2, ((pw - l2.get_width()) // 2, 18 + l1.get_height() + 16))
            screen.blit(panel, ((w - pw) // 2, (h - ph) // 2))
        except Exception:
            pass
    try:
        pygame.display.flip()
    except Exception:
        pass


def _set_all_hdmi(config, screens, on):
    """Power every photo screen's HDMI off (F9 blackout) or restore the canonical
    side-by-side layout (wake). Restore uses --right-of so it can't mirror."""
    try:
        from modules.screen_power import output_power, restore_side_by_side
    except Exception:
        return
    if on:
        restore_side_by_side(config)      # geometry-independent; heals mirroring
        return
    photo_screens = [(t, s) for t, s in screens.items()
                     if t.startswith("portrait") or t.startswith("landscape")]
    ids = [config.get("screen1_display_id", 2), config.get("screen2_display_id", 7)]
    names = [config.get("screen1_output", "HDMI-1"), config.get("screen2_output", "HDMI-2")]
    for idx, (stype, screen) in enumerate(photo_screens):
        output_power(ids[idx] if idx < len(ids) else None, False,
                     names[idx] if idx < len(names) else None)


def _maybe_sprinkle(state, config, current_ts):
    """Release one on-this-day flashback into the queue every
    on_this_day_interval_minutes, when sprinkle mode is on."""
    pool = state.get("sprinkle_pool")
    if not pool:
        return
    if current_ts < state.get("next_sprinkle", 0):
        return
    from collections import deque
    item = pool.popleft()
    fq = state.get("flashback_queue")
    if not isinstance(fq, deque):
        fq = deque()
        state["flashback_queue"] = fq
    fq.appendleft(item)   # show it on the next rotation
    state["next_sprinkle"] = current_ts + config.get("on_this_day_interval_minutes", 30) * 60


def _build_band_overlay(screen, config):
    """Pre-render the persistent time/weather band onto a transparent layer so
    the transition can keep it visible. Returns None when persist mode is off or
    nothing is enabled/available to draw."""
    if not config.get("overlay_band_persist", True):
        return None
    status_on = config.get("status_line_enabled", False)
    pill_on = config.get("weather_pill_enabled", False)
    if not (status_on or pill_on):
        return None
    try:
        layer = pygame.Surface(screen.get_size(), pygame.SRCALPHA)
        drew = False
        if status_on:
            drew = draw_status_line(screen, config, layer) or drew
        if pill_on:
            drew = draw_weather_pill(screen, config, layer) or drew
        return layer if drew else None
    except Exception as e:
        log_error(f"Band overlay build failed: {e}")
        return None


def _render_frame(screen, frame, config, media_log):
    """Render an already-decided frame: {"mode", "picks", "caption"}."""
    try:
        mode, picks = frame["mode"], frame["picks"]
        cap_override = frame.get("caption")
        band = _build_band_overlay(screen, config)
        if mode == "single":
            f = picks[0]
            if f.lower().endswith(VIDEO_EXTS):
                fd, cap = _get_media_metadata(f, media_log)
                show_video(screen, f, config, fd, cap)
                try:
                    from modules.display_handler import set_photo_rects
                    set_photo_rects(screen, [(f, pygame.Rect(0, 0, *screen.get_size()))])
                except Exception:
                    pass
            else:
                fd, cap = ((None, cap_override) if cap_override is not None
                           else _get_media_metadata(f, media_log))
                show_layout(screen, [f], config, "single", file_meta=(fd, cap), overlay=band)
            _set_now_showing(f)
        else:
            show_layout(screen, picks, config, mode, overlay=band)
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


def _render_screen(screen, screen_type, files, state, config, media_log, multi_files=None):
    """Render the next slideshow frame for one screen, with random layout variety,
    recording it so the arrows can browse back/forward through full renders.

    Videos always play full-screen; recently-shown photos are skipped. Multi-photo
    layouts pull from multi_files (the opposite-orientation pool) so the cells fit:
    a landscape screen's tall tile cells get portraits, and vice versa.
    """
    # F8 per-screen feature queue: orientation-matched, one screen only. Plays
    # ahead of everything else; drains then normal programming resumes.
    fbs = state.get("feature_by_screen")
    if fbs:
        dq = fbs.get(screen_type)
        while dq:
            path, caption = dq.popleft()
            if os.path.exists(path) and not path.lower().endswith(VIDEO_EXTS):
                frame = {"mode": "single", "picks": [path], "caption": caption}
                _push_history(state, screen_type, frame)
                _render_frame(screen, frame, config, media_log)
                _mark_shown(state, [path], config, len(files))
                return
        if dq is not None:                 # this screen's queue is now empty
            fbs.pop(screen_type, None)

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

    # Gather N images for the layout. Tile/split fit the opposite-orientation
    # pool (portraits in a landscape screen's narrow columns); cascade stacks
    # photos diagonally, so it needs same-orientation photos (landscape on the
    # landscape screen) — opposite portraits would run off the top/bottom.
    need = layout_file_count(mode)
    skip_recent = config.get("recent_memory_enabled", True)
    if mode in ("tile3", "tile6", "split") and multi_files:
        pool = multi_files
    else:
        pool = files

    def _eligible(allow_recent):
        return [f for f in pool if not f.lower().endswith(VIDEO_EXTS)
                and (allow_recent or not (skip_recent and _is_recent(state, f)))]

    cands = _eligible(False)
    if len(cands) < need:
        cands = _eligible(True)

    if len(cands) >= need:
        shuffle(cands)
        picks = cands[:need]
        frame = {"mode": mode, "picks": picks, "caption": None}
        _push_history(state, screen_type, frame)
        _render_frame(screen, frame, config, media_log)
        _mark_shown(state, picks, config, len(pool))
    else:                                   # not enough — fall back to single
        frame = {"mode": "single", "picks": [first], "caption": None}
        _push_history(state, screen_type, frame)
        _render_frame(screen, frame, config, media_log)
        _mark_shown(state, [first], config, len(files))
    state[screen_type]["index"] = (idx + 1) % len(files)


def _render_one_screen(screen_type, screen, portrait_files, landscape_files,
                       state, config, media_log, is_single, current_ts):
    """Render one photo screen (placeholder if it has no media). Honors pause."""
    if current_ts < state.get(screen_type, {}).get("paused_until", 0):
        return
    if is_single:
        files = list(dict.fromkeys(portrait_files + landscape_files))
        multi_files = files
    else:
        portrait = screen_type.startswith("portrait")
        files = portrait_files if portrait else landscape_files
        # Multi-photo grids fit the opposite orientation; toggle off to keep
        # same-orientation tiling.
        if config.get("multi_opposite_orientation", True):
            multi_files = landscape_files if portrait else portrait_files
        else:
            multi_files = files
        if not multi_files:           # opposite pool empty — fall back to same
            multi_files = files
    if not files:
        try:
            screen.fill((20, 20, 40))
            font = pygame.font.Font(None, 36)
            text = font.render("Selah - Waiting for photos...", True, (150, 150, 150))
            screen.blit(text, text.get_rect(center=screen.get_rect().center))
            pygame.display.flip()
        except Exception:
            pass
        return
    _render_screen(screen, screen_type, files, state, config, media_log, multi_files)


def _fade_in_layer(screen, bg, layer, seconds):
    """Fade `layer` (a per-pixel-alpha surface) up over `bg` across `seconds`."""
    try:
        steps = 30
        delay = max(10, int(seconds * 1000 / steps))
        for i in range(1, steps + 1):
            a = int(255 * i / steps)
            tmp = layer.copy()
            # Scale the layer's alpha channel by a/255 (works on SRCALPHA surfaces,
            # where a plain set_alpha is ignored).
            tmp.fill((255, 255, 255, a), special_flags=pygame.BLEND_RGBA_MULT)
            screen.blit(bg, (0, 0))
            screen.blit(tmp, (0, 0))
            pygame.display.flip()
            pygame.time.delay(delay)
        screen.blit(bg, (0, 0))
        screen.blit(layer, (0, 0))
        pygame.display.flip()
    except Exception as e:
        log_error(f"Overlay fade-in failed: {e}")


def _draw_time_weather(screens, config, fade):
    """Draw the persistent time / weather-pill overlays, fading them in gently
    after a fresh photo (fade=True) or drawing them instantly (fade=False)."""
    status_on = config.get("status_line_enabled", False)
    pill_on = config.get("weather_pill_enabled", False)
    if not (status_on or pill_on):
        return
    do_fade = fade and config.get("overlay_fade_in_enabled", True)
    seconds = float(config.get("overlay_fade_seconds", 2.5))
    for screen in screens.values():
        if do_fade:
            bg = screen.copy()
            layer = pygame.Surface(screen.get_size(), pygame.SRCALPHA)
            drew = False
            if status_on:
                drew = draw_status_line(screen, config, layer) or drew
            if pill_on:
                drew = draw_weather_pill(screen, config, layer) or drew
            if drew:
                _fade_in_layer(screen, bg, layer, seconds)
        else:
            if status_on:
                draw_status_line(screen, config, screen)
            if pill_on:
                draw_weather_pill(screen, config, screen)
    if not do_fade:
        try:
            pygame.display.flip()
        except Exception:
            pass


def _blit_image_fill(surface, path):
    """Cover-scale an image to fill `surface` (centered, cropped)."""
    try:
        from modules.display_handler import _load_surface
        img = _load_surface(path)
        if not img:
            return
        sw, sh = surface.get_size()
        iw, ih = img.get_size()
        scale = max(sw / iw, sh / ih)
        img = pygame.transform.smoothscale(img, (max(1, int(iw * scale)), max(1, int(ih * scale))))
        surface.fill((0, 0, 0))
        surface.blit(img, ((sw - img.get_width()) // 2, (sh - img.get_height()) // 2))
    except Exception as e:
        log_error(f"Sunrise image blit failed: {e}")


def _draw_night(screens, config):
    """Draw the night display once and return the list of clock target surfaces
    to keep refreshing for a sweeping second hand.

    The 'info' screen (night_info_screen) shows the moon — or a sunrise photo
    near sunrise — alongside the clock; the other screen is blanked (portrait
    off) or also shows a clock."""
    targets = []
    photo_screens = [(t, s) for t, s in screens.items()
                     if t.startswith("portrait") or t.startswith("landscape")]

    # night_off_mode: which screen's HDMI to power off at night (1/2/both/none).
    off_mode = config.get("night_off_mode", "none")
    off_idx = {"1": {0}, "2": {1}, "both": {0, 1}}.get(off_mode, set())
    disp_ids = [config.get("screen1_display_id", 2), config.get("screen2_display_id", 7)]
    out_names = [config.get("screen1_output", "HDMI-1"), config.get("screen2_output", "HDMI-2")]
    try:
        from modules.screen_power import output_power
    except Exception:
        output_power = None

    # Power each screen's HDMI on/off per the mode, and note which are still on.
    on_screens = []
    for idx, (stype, screen) in enumerate(photo_screens):
        did = disp_ids[idx] if idx < len(disp_ids) else None
        name = out_names[idx] if idx < len(out_names) else None
        try:
            ox, oy = screen.get_offset()      # exact xrandr layout position
            pos = f"{ox}x{oy}"
        except Exception:
            pos = None
        if idx in off_idx:
            if output_power and (did is not None or name):
                output_power(did, False, name)
            screen.fill((0, 0, 0))
        else:
            if output_power and (did is not None or name):
                output_power(did, True, name, pos)
            on_screens.append((stype, screen))

    if not on_screens:
        try:
            pygame.display.flip()
        except Exception:
            pass
        return targets

    # Sunrise/sunset photo takes the moon's place during its window.
    sunrise_img = None
    try:
        from modules import sunrise as _sunrise
        sunrise_img = _sunrise.active_image(config)
    except Exception:
        pass

    # Info screen (moon/clock) = an ON screen, preferring night_info_screen.
    pref = config.get("night_info_screen", "landscape")
    info_t = next((t for t, _ in on_screens if t.startswith(pref)), on_screens[0][0])

    for stype, screen in on_screens:
        if stype == info_t:
            w, h = screen.get_size()
            half = w // 2
            try:
                left = screen.subsurface((0, 0, half, h))
                right = screen.subsurface((half, 0, w - half, h))
            except Exception:
                left = right = screen
            if sunrise_img:
                _blit_image_fill(left, sunrise_img)
            elif config.get("moon_phase_enabled", True):
                show_moon_phase(left, config)
            targets.append(right)
        else:
            screen.fill((0, 0, 0))
    try:
        pygame.display.flip()
    except Exception:
        pass
    return targets


def _sweep_clocks(targets, config, seconds):
    """Redraw the analog clock(s) a few times a second for `seconds` so the
    second hand sweeps. The moon stays put (drawn once). Returns early on input."""
    interrupt = (pygame.QUIT, pygame.KEYDOWN, pygame.MOUSEBUTTONDOWN, pygame.FINGERDOWN)
    end = time.time() + max(0.0, seconds)
    if not targets:
        _responsive_sleep(seconds)
        return
    while time.time() < end:
        for t in targets:
            show_clock_with_quote(t, config)
        try:
            pygame.event.pump()           # peek alone doesn't poll the OS queue
            if pygame.event.peek(interrupt):
                return
        except Exception:
            pass
        pygame.time.delay(200)   # ~5 fps — smooth enough for a sweep


def _delete_to_trash(path):
    """Move a photo out of the library into a recoverable 'deleted/' folder.
    Returns True on success. Kept out of media/ so it leaves the rotation."""
    import shutil
    try:
        if not path or not os.path.exists(path):
            return False
        trash = os.path.join(os.getcwd(), "deleted")
        os.makedirs(trash, exist_ok=True)
        dest = os.path.join(trash, os.path.basename(path))
        if os.path.exists(dest):
            base, ext = os.path.splitext(os.path.basename(path))
            dest = os.path.join(trash, f"{base}_{int(os.path.getmtime(path))}{ext}")
        shutil.move(path, dest)
        return True
    except Exception as e:
        log_error(f"Delete failed for {path}: {e}")
        return False


def _draw_number_badge(screen, rect, n):
    """Draw a big yellow number badge in the top-left corner of a photo rect."""
    try:
        w, h = screen.get_size()
        fs = max(48, min(rect.width, rect.height) // 4, w // 16)
        font = pygame.font.Font(None, fs)
        label = font.render(str(n), True, (20, 20, 20))
        pad = fs // 4
        bw, bh = label.get_width() + pad * 2, label.get_height() + pad * 2
        # Anchor inside the photo's top-left, clamped to the screen.
        bx = max(4, min(rect.left + 8, w - bw - 4))
        by = max(4, min(rect.top + 8, h - bh - 4))
        badge = pygame.Surface((bw, bh), pygame.SRCALPHA)
        pygame.draw.rect(badge, (255, 214, 10, 235), (0, 0, bw, bh), border_radius=bh // 4)
        pygame.draw.rect(badge, (40, 40, 40, 235), (0, 0, bw, bh), width=max(2, fs // 20),
                         border_radius=bh // 4)
        badge.blit(label, (pad, pad))
        screen.blit(badge, (bx, by))
    except Exception:
        pass


def _prompt_pick_photo(screens, numbered, verb="Delete"):
    """Overlay a yellow number on each displayed photo and let the user type the
    one to act on. Keeps the photos visible while choosing. Returns the chosen
    0-based index, or None if cancelled/invalid."""
    photo_screens = [(t, s) for t, s in screens.items()
                     if t.startswith(("portrait", "landscape"))]
    hint_screen = screens.get("landscape") or screens.get("portrait")
    clock = pygame.time.Clock()
    pygame.event.clear()
    entered = ""

    def _redraw():
        for i, (_scr_t, _scr, rect, _path) in enumerate(numbered, start=1):
            _draw_number_badge(_scr, rect, i)
        if hint_screen:
            w, h = hint_screen.get_size()
            font = pygame.font.Font(None, max(28, w // 34))
            msg = (f"{verb} which photo?  {entered or '—'}    "
                   f"(1–{len(numbered)}, Enter, Esc)")
            txt = font.render(msg, True, (255, 255, 255))
            bar = pygame.Surface((txt.get_width() + 40, txt.get_height() + 24),
                                 pygame.SRCALPHA)
            bar.fill((0, 0, 0, 210))
            bar.blit(txt, (20, 12))
            hint_screen.blit(bar, ((w - bar.get_width()) // 2, h - bar.get_height() - 24))
        try:
            pygame.display.flip()
        except Exception:
            pass

    while True:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                return None
            if event.type != pygame.KEYDOWN:
                continue
            if event.key == pygame.K_ESCAPE:
                return None
            if event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                if entered.isdigit() and 1 <= int(entered) <= len(numbered):
                    return int(entered) - 1
                entered = ""     # invalid — clear and let them retype
            elif event.key == pygame.K_BACKSPACE:
                entered = entered[:-1]
            elif event.unicode and event.unicode.isdigit() and len(entered) < 3:
                entered += event.unicode
        _redraw()
        clock.tick(30)


def _responsive_sleep(seconds):
    """Sleep up to `seconds`, but return the instant an input event is queued so
    arrows / spacebar / F-keys / touch act immediately instead of waiting out
    the rest of the current rotation."""
    interrupt = (pygame.QUIT, pygame.KEYDOWN, pygame.MOUSEBUTTONDOWN, pygame.FINGERDOWN)
    end = time.time() + max(0.0, seconds)
    while time.time() < end:
        try:
            pygame.event.pump()           # peek alone doesn't poll the OS queue
            if pygame.event.peek(interrupt):
                return  # leave it queued; the top of the loop handles it
        except Exception:
            pass
        pygame.time.delay(40)


def _render_screen_with_panel(screen_type, screen, portrait_files, landscape_files,
                              state, config, media_log, is_single, current_ts,
                              panel_kind, side):
    """Split one screen: an info panel (agenda/forecast) on one half, the photo
    slideshow rendered into the other half. Returns the photo half subsurface
    (for overlays), or None on failure."""
    w, h = screen.get_size()
    if h > w:
        # Portrait screen: split top/bottom with the panel along the bottom.
        half = h // 2
        photo_rect, panel_rect = (0, 0, w, half), (0, half, w, h - half)
    elif side == "left":
        half = w // 2
        panel_rect, photo_rect = (0, 0, half, h), (half, 0, w - half, h)
    else:
        half = w // 2
        photo_rect, panel_rect = (0, 0, half, h), (half, 0, w - half, h)
    try:
        photo_sub = screen.subsurface(photo_rect)
        panel_sub = screen.subsurface(panel_rect)
    except Exception as e:
        log_error(f"Panel split failed: {e}")
        _render_one_screen(screen_type, screen, portrait_files, landscape_files,
                           state, config, media_log, is_single, current_ts)
        return None
    # Draw the panel first so it's already up while the photo half animates in;
    # the photo render only touches its own half, so the panel stays put.
    try:
        panel_sub.fill((0, 0, 0))
        if panel_kind == "forecast":
            render_forecast_panel(panel_sub, config)
        else:
            render_agenda_panel(panel_sub, config)
        pygame.display.flip()
    except Exception as e:
        log_error(f"Info panel render failed: {e}")
    _render_one_screen(screen_type, photo_sub, portrait_files, landscape_files,
                       state, config, media_log, is_single, current_ts)
    return photo_sub


def _draw_overlays(screens, config, fade=False):
    """Draw every overlay on top of the freshly rendered photo(s).

    Must run AFTER the slideshow render — otherwise the photo covers them.
    Pass a subset of screens (staggered mode) to draw on just those.
    fade=True gently fades the time/weather overlays in after a new photo.
    """
    try:
        show_toast_if_needed(screens, config)
        if config.get("verse_display_enabled", False):
            show_verse_if_scheduled(screens, config)
        # When the split info panel is on, the agenda/forecast are rendered into
        # half the screen by the main loop instead of as full-screen overlays.
        if not config.get("info_panel_split", True):
            if config.get("calendar_display_enabled", False):
                show_calendar_if_scheduled(screens, config)
            if config.get("weather_enabled", False):
                show_weather_if_scheduled(screens, config)
        _draw_time_weather(screens, config, fade)
        if config.get("upload_qr_enabled", False):
            show_upload_qr_if_scheduled(screens, config)
        if config.get("coming_up_enabled", False):
            show_coming_up_if_scheduled(screens, config)
        show_pending_badge(screens, config)
    except Exception as e:
        log_error(f"Overlay draw failed: {e}")


def main():
    print("[Selah] Starting display system...")
    config = load_config("display_config.json")

    # Apply timezone first so all scheduling (day/night, agenda, special days)
    # runs in the configured zone (e.g. Eastern with auto DST).
    apply_timezone(config)

    # Assert the side-by-side dual layout BEFORE building the window, so a
    # mirrored/overlapped X state (both HDMIs stuck at 0x0) is healed and the
    # app spans both monitors instead of duplicating onto both.
    if config.get("enforce_dual_layout", True):
        try:
            from modules.screen_power import restore_side_by_side
            restore_side_by_side(config)
        except Exception as e:
            log_error(f"Dual-layout assert failed: {e}")

    # Initialize displays
    screens = init_displays(config)
    if not screens:
        log_error("No displays initialized. Exiting.", critical=True, config=config)
        print("[Selah] ERROR: No displays could be initialized.")
        return

    print(f"[Selah] Initialized screens: {list(screens.keys())}")

    # Stop the OS from blanking/sleeping the screens during the slideshow.
    if config.get("prevent_screen_sleep", True):
        from modules.screen_power import prevent_sleep
        prevent_sleep()

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
        last_awake_assert = 0
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

            # Refresh moonrise/moonset once a day (background, self-throttling).
            if config.get("moon_phase_enabled", True):
                try:
                    from modules.moon_times import refresh_moon_times
                    refresh_moon_times(config)
                except Exception:
                    pass

            # On-this-day flashbacks — queue once each morning.
            _check_flashbacks(state, config, portrait_files, landscape_files, screens)
            # Sprinkle mode: release a memory into the queue every so often.
            _maybe_sprinkle(state, config, current_ts)

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
                    # An F9 blackout (or its preview) is cancelled by any nav/space
                    # press — wakes the screens and clears the stack.
                    if (state.get("blackout_until", 0) > current_ts
                            or state.get("blackout_show_until", 0) > current_ts) and event.key in (
                            pygame.K_SPACE, pygame.K_LEFT, pygame.K_RIGHT,
                            pygame.K_UP, pygame.K_DOWN):
                        state["blackout_until"] = 0
                        state["blackout_show_until"] = 0
                        state["blackout_hours"] = 0
                        continue
                    if event.key == pygame.K_ESCAPE:
                        print("[Selah] ESC pressed - shutting down.")
                        pygame.quit()
                        return
                    elif event.key == pygame.K_F1:
                        target = screens.get("landscape") or screens.get("portrait")
                        show_config_gui(target, config, screens)
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
                    elif event.key == pygame.K_F6:
                        # Manually show the info panel: agenda -> 5-day -> off.
                        nxt = {None: "agenda", "agenda": "forecast",
                               "forecast": None}[state.get("manual_panel")]
                        state["manual_panel"] = nxt
                        state["manual_panel_until"] = current_ts + config.get(
                            "manual_panel_seconds", 120)
                        show_toast_if_needed(screens, config,
                                             {"agenda": "Agenda",
                                              "forecast": "5-day forecast",
                                              None: "Panel hidden"}[nxt])
                    elif event.key == pygame.K_DELETE:
                        # Number every displayed photo, let the user pick which,
                        # then confirm with the PIN — so it's unambiguous which
                        # photo (and which screen) gets deleted.
                        if config.get("delete_enabled", True):
                            from modules.display_handler import get_photo_rects
                            numbered = []   # (screen_type, screen, rect, path)
                            for _st, _sc in screens.items():
                                if _st.startswith(("portrait", "landscape")):
                                    for _p, _r in get_photo_rects(_sc):
                                        numbered.append((_st, _sc, _r, _p))
                            target = screens.get("landscape") or screens.get("portrait")
                            if not numbered:
                                show_toast_if_needed(screens, config, "Nothing to delete")
                            elif target:
                                choice = _prompt_pick_photo(screens, numbered, verb="Delete")
                                if choice is None:
                                    state["nav_request"] = 1   # clear badges, move on
                                else:
                                    cur = numbered[choice][3]
                                    from modules.pin_prompt import prompt_pin
                                    entered = prompt_pin(target, f"Delete photo {choice + 1} — enter code")
                                    if entered is None:
                                        state["nav_request"] = 1
                                    elif entered == str(config.get("delete_pin", "8719")):
                                        if _delete_to_trash(cur):
                                            portrait_files[:] = [f for f in portrait_files if f != cur]
                                            landscape_files[:] = [f for f in landscape_files if f != cur]
                                            state["nav_request"] = 1  # advance off the deleted pic
                                            show_toast_if_needed(screens, config, "Photo deleted")
                                        else:
                                            show_toast_if_needed(screens, config, "Delete failed")
                                    else:
                                        show_toast_if_needed(screens, config, "Wrong code")
                    elif event.key == pygame.K_F7:
                        # Show today's on-this-day memories now (queue them up).
                        try:
                            from collections import deque
                            files = list(dict.fromkeys(portrait_files + landscape_files))
                            fb = todays_flashbacks(files, config)
                            shuffle(fb)
                            fq = state.get("flashback_queue")
                            if not isinstance(fq, deque):
                                fq = deque()
                                state["flashback_queue"] = fq
                            for path, year in reversed(fb[:20]):
                                fq.appendleft((path, f"On this day, {year}"))
                            show_toast_if_needed(
                                screens, config,
                                f"On this day — {len(fb[:20])} memor{'y' if len(fb[:20])==1 else 'ies'}"
                                if fb else "No memories for today")
                        except Exception as e:
                            log_error(f"F7 on-this-day failed: {e}")
                    elif event.key == pygame.K_F8:
                        # Feature every new photo from the last few days now, then
                        # normal programming resumes once the queue drains. Each
                        # photo is routed to a screen matching its orientation and
                        # shown on only ONE screen (no cross-screen duplicates).
                        try:
                            from collections import deque
                            days = int(config.get("feature_new_days", 3) or 3)
                            items = _recent_media_items(config, days)
                            if items:
                                total = _queue_feature_by_orientation(
                                    items, screens, portrait_files,
                                    landscape_files, state,
                                    opposite=config.get("feature_opposite_orientation", False))
                                # Clear any manual pause so the queue plays now.
                                for _st in screens:
                                    if _st.startswith(("portrait", "landscape")):
                                        state.setdefault(_st, {})["paused_until"] = 0
                                state["paused"] = False
                                show_toast_if_needed(
                                    screens, config,
                                    f"Featuring {total} new photo(s) "
                                    f"from the last {days} days")
                            else:
                                show_toast_if_needed(
                                    screens, config,
                                    f"No new photos in the last {days} days")
                        except Exception as e:
                            log_error(f"F8 feature-recent failed: {e}")
                    elif event.key == pygame.K_F9:
                        # Stack an hour (cap 6) and show the running total on-screen
                        # for a few seconds; the blackout applies once the preview
                        # window elapses. Pressing F9 while already blanked wakes the
                        # screens and re-arms so you can see/adjust the stack.
                        if state.get("blackout_active"):
                            try:
                                from modules.screen_power import screen_on
                                screen_on()
                            except Exception:
                                pass
                            state["blackout_active"] = False
                        state["blackout_hours"] = min(6, state.get("blackout_hours", 0) + 1)
                        state["blackout_show_until"] = current_ts + 5   # preview window
                        state["blackout_until"] = 0                     # commit after preview
                    elif event.key == pygame.K_F10:
                        # Fix a photo's caption: pick it by number, edit inline, save.
                        from modules.display_handler import get_photo_rects
                        numbered = []
                        for _st, _sc in screens.items():
                            if _st.startswith(("portrait", "landscape")):
                                for _p, _r in get_photo_rects(_sc):
                                    numbered.append((_st, _sc, _r, _p))
                        target = screens.get("landscape") or screens.get("portrait")
                        if not numbered:
                            show_toast_if_needed(screens, config, "No photo to edit")
                        elif target:
                            choice = _prompt_pick_photo(screens, numbered, verb="Edit caption for")
                            state["nav_request"] = 1   # clear badges either way
                            if choice is not None:
                                cur_path = numbered[choice][3]
                                from modules.caption_edit import get_caption, update_caption
                                from modules.text_prompt import prompt_text
                                old_cap = get_caption(cur_path)
                                new_cap = prompt_text(target, "Edit caption", old_cap)
                                if new_cap is not None and new_cap != old_cap:
                                    n = update_caption(cur_path, new_cap)
                                    media_log = _load_media_log()   # reflect it now
                                    show_toast_if_needed(
                                        screens, config,
                                        "Caption updated" if n else "Couldn't save caption")
                    elif event.key in (pygame.K_h, pygame.K_QUESTION) or event.unicode == "?":
                        from modules.help_overlay import show_help
                        target = screens.get("landscape") or screens.get("portrait")
                        if target:
                            show_help(target, config)
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

            # ---- MANUAL BLACKOUT (F9): displays to standby for a set time ----
            # Uses DPMS (layout-safe) — never touches the xrandr arrangement, so
            # it can't mirror the screens.
            # 1) Preview window: show the accumulating stack, screens stay ON.
            if current_ts < state.get("blackout_show_until", 0):
                _draw_blackout_preview(screens, state.get("blackout_hours", 1))
                _responsive_sleep(0.4)   # responsive to more F9 presses / cancel
                continue
            # 2) Preview elapsed but not yet committed -> apply the blackout now.
            if (state.get("blackout_hours", 0) > 0
                    and not state.get("blackout_until", 0)
                    and not state.get("blackout_active")):
                state["blackout_until"] = current_ts + state["blackout_hours"] * 3600
            # 3) Blanked window.
            if current_ts < state.get("blackout_until", 0):
                if not state.get("blackout_active"):
                    state["blackout_active"] = True
                    for screen in screens.values():   # paint black once, then standby
                        try:
                            screen.fill((0, 0, 0))
                        except Exception:
                            pass
                    try:
                        pygame.display.flip()
                    except Exception:
                        pass
                    try:
                        from modules.screen_power import screen_off
                        screen_off()
                    except Exception:
                        pass
                # Keep intake alive while dark so submissions still land.
                if current_ts - last_email_check > email_check_interval:
                    try:
                        check_for_new_emails(config, screens)
                    except Exception:
                        pass
                    last_email_check = current_ts
                _responsive_sleep(5)   # stays responsive to F9-again / wake keys
                continue
            elif state.get("blackout_active") or state.get("blackout_hours", 0):
                # Ended (timer elapsed) or cancelled -> wake and reset the stack.
                if state.get("blackout_active"):
                    try:
                        from modules.screen_power import screen_on
                        screen_on()
                    except Exception:
                        pass
                    show_toast_if_needed(screens, config, "Welcome back")
                state["blackout_active"] = False
                state["blackout_hours"] = 0
                state["blackout_until"] = 0

            # ---- NIGHT MODE ----
            if is_display_off(current_time, config):
                # Night light: detect motion in the dark even though the
                # slideshow is off — this is exactly when the light is wanted.
                if config.get("night_light_enabled", False) and config.get("motion_detection_enabled", False):
                    try:
                        detect_motion(config, screens)
                    except Exception as e:
                        log_error(f"Night-mode motion check failed: {e}")

                verse_now = False
                if config.get("verse_display_enabled", False):
                    try:
                        from modules.verse_handler import is_verse_time, show_verse_if_scheduled
                        verse_now = is_verse_time(config)
                    except Exception:
                        verse_now = False

                if verse_now:
                    # Verse of the day at its scheduled night time, on its screen(s).
                    show_verse_if_scheduled(screens, config)
                    time.sleep(3)
                else:
                    # _draw_night powers off screens per night_off_mode and
                    # shows the moon/clock on whichever stays on.
                    targets = _draw_night(screens, config)
                    _sweep_clocks(targets, config, 10)
                # Still check email during night mode
                if current_ts - last_email_check > email_check_interval:
                    check_for_new_emails(config, screens)
                    last_email_check = current_ts
                # Keep pulling from Drive overnight (background; folds into the
                # rotation when the display wakes in the morning).
                if (config.get("cloud_backup_enabled", False)
                        and current_ts - last_drive_sync > drive_sync_interval
                        and not is_syncing()):
                    start_background_sync(config)
                    last_drive_sync = current_ts
                continue

            # Daytime: make sure both HDMIs are on if night mode turned one off,
            # restored side-by-side (--right-of, so it can never mirror at 0x0).
            if config.get("night_off_mode", "none") != "none":
                try:
                    from modules.screen_power import restore_side_by_side, is_off
                    from modules.screen_power import _out_state
                    # Only re-assert when something was actually powered off.
                    names = [config.get("screen1_output", "HDMI-1"),
                             config.get("screen2_output", "HDMI-2")]
                    if any(_out_state.get(n) is False for n in names):
                        restore_side_by_side(config)
                except Exception:
                    pass

            # Re-queue today's greetings each hour so they recur through the day.
            _maybe_hourly_greetings(state, config)
            # Feature recently-submitted photos for their first few days.
            _maybe_feature_recent(state, config)

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
                # Nudge senders who've gone quiet (self-throttles per person).
                try:
                    send_inactivity_nudges(config)
                except Exception as e:
                    log_error(f"Inactivity nudge check failed: {e}")
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

            # ---- KEEP-AWAKE (re-assert no-blank/no-DPMS, throttled) ----
            # Some environments reset xset settings; re-apply periodically, but
            # not while the screen is intentionally blanked for night mode.
            if config.get("prevent_screen_sleep", True) and current_ts - last_awake_assert > 240:
                try:
                    from modules.screen_power import prevent_sleep, is_off
                    if not is_off():
                        prevent_sleep()
                except Exception:
                    pass
                last_awake_assert = current_ts

            # ---- GOOGLE DRIVE SYNC (throttled, runs in the background) ----
            # The sync downloads on a daemon thread so the slideshow never
            # stalls; we pick up its result on a later loop iteration.
            if (config.get("cloud_backup_enabled", False)
                    and current_ts - last_drive_sync > drive_sync_interval
                    and not is_syncing()):
                start_background_sync(config)
                last_drive_sync = current_ts

            drive_result = take_sync_result()
            if drive_result:
                downloaded, uploaded, family_added = drive_result
                if downloaded:
                    print(f"[Selah] Drive sync: {downloaded} new photo(s)")
                    last_media_refresh = 0  # fold new photos into rotation promptly
                # One toast per sync that brought new shared-folder uploads —
                # the "someone added to the folder" alert, not per-pic and not
                # for the personal-folder bulk sync.
                if family_added:
                    show_toast_if_needed(screens, config,
                                         f"{family_added} new photo(s) shared!")

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

            # ---- IMMEDIATE DISPLAY of new arrivals ----
            # A just-emailed photo is surfaced at the very NEXT rotation, on the
            # correctly-oriented screen (via the same per-screen feature queue as
            # F8), then normal programming continues.
            try:
                from modules.pending_photos import take_all as _take_new
                _new = _take_new()
            except Exception:
                _new = []
            if _new and config.get("immediate_display", True):
                _queue_feature_by_orientation(
                    [(p, None) for p in _new], screens, portrait_files,
                    landscape_files, state,
                    opposite=config.get("feature_opposite_orientation", False),
                    front=True)
                for _st in screens:               # clear any manual pause
                    if _st.startswith(("portrait", "landscape")):
                        state.setdefault(_st, {})["paused_until"] = 0
                state["paused"] = False
                last_media_refresh = 0            # also fold into normal rotation promptly

            # ---- VOICE CONTROL ----
            if config.get("voice_control_enabled", False):
                process_voice_command(screens, config, state, portrait_files, landscape_files)

            # ---- SLIDESHOW + OVERLAYS ----
            # Overlays are drawn AFTER the photo so they sit on top instead of
            # being covered (that's why the weather/calendar weren't showing).
            active = (not state.get("paused", False)) and (
                state.get("slideshow_active", True) or not config.get("motion_triggered_slideshow", False))
            photo_screens = [(t, s) for t, s in screens.items()
                             if t.startswith("portrait") or t.startswith("landscape")]
            is_single = len(photo_screens) == 1
            stagger = (not config.get("screen_rotation_sync", True)) and len(photo_screens) >= 2
            # In persist mode the band rides the transition itself, so the
            # post-render overlay pass draws it instantly (no separate fade-in).
            fade_band = not config.get("overlay_band_persist", True)

            # ---- SPLIT INFO PANEL (agenda / 5-day forecast on one half) ----
            # Arm/detect each loop so the schedule still fires; photos keep
            # rotating (all layouts) on the other half during the window.
            panel_kind = None
            if config.get("info_panel_split", True):
                if config.get("weather_enabled", False) and tick_forecast(config):
                    panel_kind = "forecast"
                elif config.get("calendar_display_enabled", False) and agenda_in_window(config):
                    panel_kind = "agenda"

            # F6 manual override wins, and works even outside scheduled windows.
            manual = state.get("manual_panel")
            if manual and current_ts < state.get("manual_panel_until", 0):
                panel_kind = manual
            elif manual:
                state["manual_panel"] = None  # expired

            # ---- SUNRISE SPLIT (daytime sunrise window) ----
            # During the +/-5 min sunrise window, split the screen: sunrise on
            # the LEFT if the agenda/5-day panel is up (panel stays right), else
            # sunrise on the RIGHT with photos on the left.
            sunrise_img = None
            if active:
                try:
                    from modules import sunrise as _sunrise
                    sunrise_img = _sunrise.active_image(config)
                except Exception:
                    sunrise_img = None

            if active and sunrise_img:
                photo_subs = {}
                for t, s in photo_screens:
                    w, h = s.get_size()
                    half = w // 2
                    try:
                        left = s.subsurface((0, 0, half, h))
                        right = s.subsurface((half, 0, w - half, h))
                    except Exception:
                        left = right = s
                    if panel_kind:                       # sunrise left, panel right
                        _blit_image_fill(left, sunrise_img)
                        if panel_kind == "forecast":
                            render_forecast_panel(right, config)
                        else:
                            render_agenda_panel(right, config)
                    else:                                # photos left, sunrise right
                        _blit_image_fill(right, sunrise_img)
                        _render_one_screen(t, left, portrait_files, landscape_files,
                                           state, config, media_log, is_single, current_ts)
                        photo_subs[t] = left
                try:
                    pygame.display.flip()
                except Exception:
                    pass
                if photo_subs:
                    _draw_overlays(photo_subs, config, fade=fade_band)
                _responsive_sleep(rotate_interval)
                continue

            if active and panel_kind:
                side = config.get("info_panel_side", "right")
                photo_subs = {}
                for t, s in photo_screens:
                    psub = _render_screen_with_panel(
                        t, s, portrait_files, landscape_files, state, config,
                        media_log, is_single, current_ts, panel_kind, side)
                    if psub is not None:
                        photo_subs[t] = psub
                if photo_subs:
                    _draw_overlays(photo_subs, config, fade=fade_band)
                _responsive_sleep(rotate_interval)
                continue

            if active and stagger:
                # Staggered: render the first screen, then the rest a half-interval
                # later, so the two screens never change at the same moment. Overlays
                # are drawn per group (on a fresh photo) to avoid darkening.
                t0, s0 = photo_screens[0]
                _render_one_screen(t0, s0, portrait_files, landscape_files,
                                   state, config, media_log, is_single, current_ts)
                _draw_overlays({t0: s0}, config, fade=fade_band)
                _responsive_sleep(max(0.5, rotate_interval / 2.0))
                for t, s in photo_screens[1:]:
                    _render_one_screen(t, s, portrait_files, landscape_files,
                                       state, config, media_log, is_single, current_ts)
                _draw_overlays(dict(photo_screens[1:]), config, fade=fade_band)
                _responsive_sleep(max(0.5, rotate_interval / 2.0))
                continue

            if active:
                for t, s in photo_screens:
                    _render_one_screen(t, s, portrait_files, landscape_files,
                                       state, config, media_log, is_single, current_ts)

            _draw_overlays(screens, config, fade=active and fade_band)
            _responsive_sleep(rotate_interval)

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
            _save_recent(state)   # persist seen-history across the restart
        except Exception:
            pass
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
