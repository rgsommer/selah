"""Keyboard and touchscreen event handling for navigation."""

import time
import pygame
from modules.logger import log_error


def handle_events(screens, config, portrait_files, landscape_files, state, events=None):
    """Process keyboard/touch events for manual navigation and system control.

    Arrow keys:
        Left/Right: navigate landscape display
        Up/Down: navigate portrait display
    ESC: exit system
    F-keys handled in main loop (F1-F5)

    `events` is the already-drained event list from the main loop (so the F-key
    handler there sees the same events). Falls back to draining the queue itself
    if not provided.

    Returns updated state dict.
    """
    try:
        pause_duration = config.get("manual_navigation_pause", 60)

        if events is None:
            events = pygame.event.get()
        for event in events:
            if event.type == pygame.QUIT:
                pygame.quit()
                raise SystemExit("User quit")

            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    pygame.quit()
                    raise SystemExit("ESC pressed - exiting Selah")
                # Arrow keys + Space are handled in the main loop (they browse
                # full renders / toggle pause); we leave them for it.

            # Touchscreen swipe -> browse one step. Detect it from the whole
            # gesture (finger down -> up), NOT per-motion dx: a resting finger or
            # phantom SDL touch noise fires FINGERMOTION continuously, which used
            # to advance the photo every frame and made rotation ignore the
            # interval. A tap (tiny displacement) is ignored.
            elif event.type == pygame.FINGERDOWN:
                state["_swipe_start"] = (event.x, event.y)
            elif event.type == pygame.FINGERUP:
                start = state.get("_swipe_start")
                state["_swipe_start"] = None
                if start:
                    dx, dy = event.x - start[0], event.y - start[1]
                    if max(abs(dx), abs(dy)) > 0.12:   # deliberate swipe
                        primary = dx if abs(dx) >= abs(dy) else dy
                        state["nav_request"] = 1 if primary > 0 else -1

    except SystemExit:
        raise
    except Exception as e:
        log_error(f"Event handling error: {e}")

    return state


def _show_current(screens, screen_type, files, state, config):
    """Display the current file for a given screen type after manual navigation."""
    if screen_type not in screens or not files:
        return
    try:
        from modules.display_handler import show_image, show_video
        import json

        idx = state[screen_type]["index"]
        file_path = files[idx]

        # Try to get metadata from media_log
        file_date = None
        caption = None
        try:
            with open("media_log.json", "r") as f:
                media_log = json.load(f)
            entry = next((e for e in media_log if e.get("file_path") == file_path), None)
            if entry:
                file_date = entry.get("date")
                caption = entry.get("caption")
        except Exception:
            pass

        screen = screens[screen_type]
        if file_path.lower().endswith(('.mp4', '.avi', '.mov')):
            show_video(screen, file_path, config, file_date, caption)
        else:
            show_image(screen, file_path, config, file_date, caption)
    except Exception as e:
        log_error(f"Manual navigation display error: {e}")


def _handle_swipe(event, screens, config, portrait_files, landscape_files, state, pause_duration):
    """Handle touchscreen swipe gestures."""
    try:
        dx = event.dx
        dy = event.dy
        threshold = 0.05  # 5% of screen movement

        if abs(dx) > abs(dy) and abs(dx) > threshold:
            # Horizontal swipe -> landscape
            if landscape_files and "landscape" in state:
                direction = 1 if dx > 0 else -1
                state["landscape"]["index"] = (
                    (state["landscape"]["index"] + direction) % len(landscape_files)
                )
                state["landscape"]["paused_until"] = time.time() + pause_duration
                _show_current(screens, "landscape", landscape_files, state, config)

        elif abs(dy) > threshold:
            # Vertical swipe -> portrait
            if portrait_files and "portrait" in state:
                direction = 1 if dy > 0 else -1
                state["portrait"]["index"] = (
                    (state["portrait"]["index"] + direction) % len(portrait_files)
                )
                state["portrait"]["paused_until"] = time.time() + pause_duration
                _show_current(screens, "portrait", portrait_files, state, config)
    except Exception as e:
        log_error(f"Swipe handling error: {e}")
