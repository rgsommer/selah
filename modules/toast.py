"""Toast notification system - transient on-screen messages.

A toast shows for notification_duration seconds (default 15) then fades out and
erases itself. It saves the pixels under its bar so it can animate the fade and
clear cleanly every frame — via pump_toast() during the rotation sleep — without
re-rendering the photo/panel underneath.
"""

import time
import pygame
from modules.logger import log_error

_toast_queue = []
_current_toast = None
_toast_expire = 0
_toast_start = 0
_bg_store = {}          # id(screen) -> (rect, background copy) under the bar

FADE_IN = 0.25          # seconds to fade in
_DEFAULT_DURATION = 15


def queue_toast(message, duration=None):
    """Add a message to the toast queue."""
    _toast_queue.append({"message": message, "duration": duration})


def _alpha_for(now):
    """0..255 alpha for the current toast: quick fade-in, hold, fade-out."""
    if not _current_toast:
        return 0
    dur = max(0.1, _toast_expire - _toast_start)
    fade_out = min(2.0, max(0.6, dur * 0.2))
    rem = _toast_expire - now
    if rem <= 0:
        return 0
    elapsed = now - _toast_start
    a = 1.0
    if elapsed < FADE_IN:
        a = elapsed / FADE_IN
    if rem < fade_out:
        a = min(a, rem / fade_out)
    return max(0, min(255, int(round(a * 255))))


def is_active():
    """True while a toast is showing (or fading)."""
    return _current_toast is not None


def show_toast_if_needed(screens, config, message=None):
    """Display pending toasts. Call once per rendered frame (after the photo).

    With a message, shows it immediately; without, processes the queue. Draws the
    toast over the freshly rendered frame and remembers what was underneath so
    pump_toast() can animate/erase it between frames.
    """
    global _toast_queue, _current_toast, _toast_expire, _toast_start

    if message:
        queue_toast(message, config.get("notification_duration", _DEFAULT_DURATION))

    now = time.time()

    if _current_toast and now >= _toast_expire:
        _clear(screens)
        _current_toast = None

    if not _current_toast and _toast_queue:
        toast = _toast_queue.pop(0)
        _current_toast = toast["message"]
        duration = toast.get("duration") or config.get("notification_duration", _DEFAULT_DURATION)
        _toast_start = now
        _toast_expire = now + duration
        _bg_store.clear()
        if config.get("notification_sound_enabled", False):
            _play_sound(config.get("notification_sound_path"))

    if _current_toast:
        for screen in screens.values():
            _render_toast(screen, _current_toast, _alpha_for(now), save_bg=True)


def pump_toast(screens, config):
    """Animate the active toast's fade and erase it when expired, cheaply — only
    the bar region is touched (restored from the saved background), so the photo
    or info panel underneath is untouched. Safe to call many times per second
    during the rotation sleep. Returns True while a toast is on screen."""
    global _current_toast
    if _current_toast is None and not _bg_store:
        return False
    now = time.time()
    if _current_toast and now >= _toast_expire:
        _current_toast = None
    if _current_toast is None:
        _clear(screens)                 # restore background + flip, once
        return False
    for screen in screens.values():
        _render_toast(screen, _current_toast, _alpha_for(now),
                      save_bg=False, from_store=True)
    return True


def _bar_geometry(screen, message):
    screen_w = screen.get_width()
    font_size = max(28, screen_w // 30)
    font = pygame.font.Font(None, font_size)
    text_surface = font.render(message, True, (255, 255, 255))
    text_rect = text_surface.get_rect()
    text_rect.centerx = screen_w // 2
    text_rect.top = 20
    bar_rect = text_rect.inflate(40, 20)
    bar_rect.clamp_ip(screen.get_rect())
    return text_surface, text_rect, bar_rect


def _render_toast(screen, message, alpha, save_bg=False, from_store=False):
    """Draw the toast bar at `alpha`. save_bg captures what's underneath first;
    from_store restores that capture before drawing (to animate/erase)."""
    try:
        key = id(screen)
        text_surface, text_rect, bar_rect = _bar_geometry(screen, message)

        if from_store:
            saved = _bg_store.get(key)
            if not saved:
                return
            srect, surf = saved
            screen.blit(surf, srect.topleft)        # restore what's under the bar
        elif save_bg:
            try:
                _bg_store[key] = (bar_rect.copy(), screen.subsurface(bar_rect).copy())
            except Exception:
                pass

        if alpha > 0:
            bg_surface = pygame.Surface(bar_rect.size, pygame.SRCALPHA)
            bg_surface.fill((40, 120, 40, int(200 * alpha / 255)))
            screen.blit(bg_surface, bar_rect.topleft)
            text_surface = text_surface.copy()
            text_surface.set_alpha(alpha)
            screen.blit(text_surface, text_rect)

        try:
            pygame.display.flip()
        except Exception:
            pass
    except Exception as e:
        log_error(f"Toast render failed: {e}")


def _clear(screens):
    """Erase the toast by restoring the saved background, then flip."""
    for screen in screens.values():
        saved = _bg_store.get(id(screen))
        if saved:
            try:
                srect, surf = saved
                screen.blit(surf, srect.topleft)
            except Exception:
                pass
    try:
        pygame.display.flip()
    except Exception:
        pass
    _bg_store.clear()


def _play_sound(sound_path):
    """Play a notification sound if available."""
    try:
        if sound_path:
            import os
            if os.path.exists(sound_path):
                pygame.mixer.init()
                pygame.mixer.music.load(sound_path)
                pygame.mixer.music.play()
    except Exception:
        pass  # Sound is optional, fail silently
