"""Toast notification system - transient on-screen messages."""

import time
import pygame
from modules.logger import log_error

# Global toast queue
_toast_queue = []
_current_toast = None
_toast_expire = 0


def queue_toast(message, duration=None):
    """Add a message to the toast queue."""
    global _toast_queue
    _toast_queue.append({"message": message, "duration": duration})


def show_toast_if_needed(screens, config, message=None):
    """Display any pending toast notifications on all screens.

    Can be called with a message to show immediately, or without
    to process the queue.
    """
    global _toast_queue, _current_toast, _toast_expire

    if message:
        queue_toast(message, config.get("notification_duration", 15))

    now = time.time()

    # Check if current toast has expired
    if _current_toast and now >= _toast_expire:
        _current_toast = None

    # Pop next toast from queue if nothing showing
    if not _current_toast and _toast_queue:
        toast = _toast_queue.pop(0)
        _current_toast = toast["message"]
        duration = toast.get("duration") or config.get("notification_duration", 15)
        _toast_expire = now + duration

        # Play notification sound
        if config.get("notification_sound_enabled", False):
            _play_sound(config.get("notification_sound_path"))

    # Render current toast on all screens
    if _current_toast:
        for screen in screens.values():
            _render_toast(screen, _current_toast)


def _render_toast(screen, message):
    """Render a toast notification bar at the top of the screen."""
    try:
        screen_w = screen.get_width()
        font_size = max(28, screen.get_width() // 30)
        font = pygame.font.Font(None, font_size)

        text_surface = font.render(message, True, (255, 255, 255))
        text_rect = text_surface.get_rect()
        text_rect.centerx = screen_w // 2
        text_rect.top = 20

        # Background bar
        bar_rect = text_rect.inflate(40, 20)
        bg_surface = pygame.Surface(bar_rect.size, pygame.SRCALPHA)
        bg_surface.fill((40, 120, 40, 200))  # Green semi-transparent
        screen.blit(bg_surface, bar_rect.topleft)
        screen.blit(text_surface, text_rect)

        try:
            pygame.display.flip()
        except Exception:
            pass
    except Exception as e:
        log_error(f"Toast render failed: {e}")


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
