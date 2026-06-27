"""Theme manager for Selah Display System.

Applies seasonal/holiday themes (borders, color tints) based on date.
"""

import datetime
import pygame
from modules.logger import log_error

_current_theme = None
_last_theme_check = None


def apply_theme(screens, config):
    """Check and apply current seasonal theme. Recalculates once per hour."""
    if not config.get("theme_enabled", False):
        return

    global _current_theme, _last_theme_check

    now = datetime.datetime.now()
    if _last_theme_check and (now - _last_theme_check).seconds < 3600:
        return
    _last_theme_check = now

    new_theme = _detect_theme(now)
    if new_theme != _current_theme:
        _current_theme = new_theme
        if _current_theme:
            print(f"[Theme] Activated: {_current_theme['name']}")


def get_current_theme():
    """Return the current theme dict or None."""
    return _current_theme


def _detect_theme(now):
    """Detect which theme should be active based on the current date."""
    month = now.month
    day = now.day

    # Advent through Christmas — celebrating the birth of Christ
    if month == 12:
        return {
            "name": "Advent / Christmas",
            "border_color": (100, 50, 120),   # Royal purple for Advent
            "accent_color": (218, 165, 32),   # Gold for the King of Kings
            "overlay_alpha": 20,
            "border_width": 5,
        }
    if month == 2 and 10 <= day <= 14:
        return {
            "name": "Valentine's Day",
            "border_color": (200, 50, 80),
            "accent_color": (255, 182, 193),
            "overlay_alpha": 20,
            "border_width": 4,
        }
    # Holy Week through Resurrection Sunday
    if (month == 3 and day >= 20) or (month == 4 and day <= 20):
        return {
            "name": "Resurrection Sunday",
            "border_color": (255, 255, 255),   # White for resurrection and purity
            "accent_color": (218, 165, 32),     # Gold for glory
            "overlay_alpha": 12,
            "border_width": 4,
        }
    if month == 7 and day == 1:
        return {
            "name": "Canada Day",
            "border_color": (255, 0, 0),
            "accent_color": (255, 255, 255),
            "overlay_alpha": 20,
            "border_width": 5,
        }
    if month == 10 and 8 <= day <= 14:
        return {
            "name": "Thanksgiving",
            "border_color": (200, 120, 50),
            "accent_color": (160, 82, 45),
            "overlay_alpha": 20,
            "border_width": 4,
        }
    if month == 10 and day == 31:
        return {
            "name": "Reformation Day",
            "border_color": (139, 90, 43),
            "accent_color": (218, 165, 32),
            "overlay_alpha": 15,
            "border_width": 4,
        }
    return None


def draw_theme_border(screen):
    """Draw a themed border on the screen if a theme is active."""
    if not _current_theme:
        return
    try:
        screen_w, screen_h = screen.get_size()
        border_w = _current_theme.get("border_width", 4)
        color = _current_theme.get("border_color", (255, 255, 255))
        pygame.draw.rect(screen, color, (0, 0, screen_w, screen_h), border_w)

        alpha = _current_theme.get("overlay_alpha", 0)
        if alpha > 0:
            accent = _current_theme.get("accent_color", (255, 255, 255))
            overlay = pygame.Surface((screen_w, screen_h), pygame.SRCALPHA)
            overlay.fill((*accent, alpha))
            screen.blit(overlay, (0, 0))
    except Exception as e:
        log_error(f"Theme border draw failed: {e}")
