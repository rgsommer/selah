"""Night-time moon phase display.

Computes the current lunar phase astronomically (no network) from the synodic
month since a known new moon, and renders an accurately-lit moon disk sized to
~2/3 of the screen width — intended for one HDMI during night mode.
"""

import os
import math
import datetime

import pygame

from modules.logger import log_error

# Cache the scaled, circle-cropped moon photo so we don't re-process it each draw.
_moon_photo_cache = {"key": None, "surf": None}


def _load_moon_photo(path, size):
    """Load the user's moon image, scale to `size`, and crop to a circle."""
    try:
        key = (path, os.path.getmtime(path), size)
    except Exception:
        return None
    if _moon_photo_cache["key"] == key:
        return _moon_photo_cache["surf"]
    try:
        img = pygame.image.load(path).convert_alpha()
        img = pygame.transform.smoothscale(img, (size, size))
        mask = pygame.Surface((size, size), pygame.SRCALPHA)
        pygame.draw.circle(mask, (255, 255, 255, 255), (size // 2, size // 2), size // 2)
        moon = img.copy()
        moon.blit(mask, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)  # keep only the disk
        _moon_photo_cache["key"] = key
        _moon_photo_cache["surf"] = moon
        return moon
    except Exception as e:
        log_error(f"Moon photo load failed for {path}: {e}")
        return None


def _draw_moon_photo(screen, cx, cy, r, f, waxing, config):
    """Draw the user's moon photo with the unlit part shadowed to tonight's
    phase. Returns True if drawn."""
    path = config.get("moon_photo", "")
    if not path or not os.path.exists(path):
        return False
    size = 2 * r
    base = _load_moon_photo(path, size)
    if base is None:
        return False
    try:
        moon = base.copy()
        # Dim the whole moon so it doesn't light the room (percent of full).
        dim = int(config.get("moon_photo_brightness", 55))
        if dim < 100:
            v = max(0, min(255, int(255 * dim / 100)))
            moon.fill((v, v, v, 255), special_flags=pygame.BLEND_RGBA_MULT)
        # Shadow the unlit portion using the same terminator geometry.
        shade = pygame.Surface((size, size), pygame.SRCALPHA)
        for dy in range(-r, r + 1):
            xw = math.sqrt(max(0.0, r * r - dy * dy))
            if waxing:
                x0, x1 = (1 - 2 * f) * xw, xw        # lit span (right side)
            else:
                x0, x1 = -xw, (2 * f - 1) * xw       # lit span (left side)
            yy = r + dy
            if x0 > -xw:                              # unlit on the left
                pygame.draw.line(shade, (0, 0, 6, 232), (int(r - xw), yy), (int(r + x0), yy))
            if xw > x1:                               # unlit on the right
                pygame.draw.line(shade, (0, 0, 6, 232), (int(r + x1), yy), (int(r + xw), yy))
        moon.blit(shade, (0, 0))
        screen.blit(moon, (cx - r, cy - r))
        return True
    except Exception as e:
        log_error(f"Moon photo render failed: {e}")
        return False

_SYNODIC = 29.53058867  # days in a lunar (synodic) month
_EPOCH_NEW_MOON = datetime.datetime(2000, 1, 6, 18, 14)  # a known new moon (UTC)

# Upper bound of phase fraction for each named phase (ordered).
_PHASE_NAMES = [
    (0.02, "New Moon"),
    (0.23, "Waxing Crescent"),
    (0.27, "First Quarter"),
    (0.48, "Waxing Gibbous"),
    (0.52, "Full Moon"),
    (0.73, "Waning Gibbous"),
    (0.77, "Last Quarter"),
    (0.98, "Waning Crescent"),
]


def moon_phase_fraction(now=None):
    """Phase as a fraction 0..1 (0 = new, 0.5 = full, ->1 = next new)."""
    now = now or datetime.datetime.utcnow()
    days = (now - _EPOCH_NEW_MOON).total_seconds() / 86400.0
    return (days % _SYNODIC) / _SYNODIC


def illuminated_fraction(phase):
    """Fraction of the disk that is lit (0 = new, 1 = full)."""
    return (1 - math.cos(2 * math.pi * phase)) / 2


def phase_name(phase):
    for thresh, name in _PHASE_NAMES:
        if phase < thresh:
            return name
    return "New Moon"


def show_moon_phase(screen, config):
    """Fill the screen with a night sky and a 2/3-width moon at its real phase."""
    try:
        w, h = screen.get_size()
        screen.fill((6, 8, 18))  # deep night sky

        phase = moon_phase_fraction()
        f = illuminated_fraction(phase)
        waxing = phase < 0.5

        # 2/3 of the width, but never taller than the screen (leave text room).
        diameter = min(int(w * 2 / 3), int(h * 0.82))
        r = max(10, diameter // 2)
        cx = w // 2
        cy = int(h * 0.42)

        # Use the user's moon photo if provided, masked to tonight's phase;
        # otherwise draw a dim sepia synthetic moon.
        if not _draw_moon_photo(screen, cx, cy, r, f, waxing, config):
            lit = tuple(config.get("moon_lit_color", (120, 96, 60)))
            _draw_moon(screen, cx, cy, r, f, waxing, lit)

        # Labels: phase name + % lit, and the time (so a single-HDMI setup still
        # shows the clock). Dimmed to match the sepia moon.
        name = phase_name(phase)
        pct = int(round(f * 100))
        big = pygame.font.Font(None, max(28, w // 24))
        small = pygame.font.Font(None, max(22, w // 36))
        try:
            tstr = datetime.datetime.now().strftime("%-I:%M %p")
        except Exception:
            tstr = datetime.datetime.now().strftime("%H:%M")

        name_surf = big.render(f"{name}  -  {pct}% lit", True, (120, 102, 78))
        screen.blit(name_surf, name_surf.get_rect(center=(cx, cy + r + big.get_linesize())))
        time_surf = small.render(tstr, True, (110, 96, 74))
        screen.blit(time_surf, time_surf.get_rect(
            center=(cx, cy + r + big.get_linesize() + small.get_linesize() + 6)))

        try:
            pygame.display.flip()
        except Exception:
            pass
    except Exception as e:
        log_error(f"Moon phase render failed: {e}")


def _draw_moon(screen, cx, cy, r, f, waxing, lit=(120, 96, 60)):
    """Draw a dark disk, then fill the lit portion scanline-by-scanline.

    For each row the lit span runs between the limb and the terminator:
      waxing: x in [(1-2f)*xw, xw]      (right side lights up)
      waning: x in [-xw, (2f-1)*xw]     (left side stays lit)
    where xw = sqrt(r^2 - y^2). This is continuous through new and full.

    `lit` defaults to a dim sepia so the moon doesn't light up the room.
    """
    dark = (30, 28, 26)

    pygame.draw.circle(screen, dark, (cx, cy), r)

    for dy in range(-r, r + 1):
        xw = math.sqrt(max(0.0, r * r - dy * dy))
        if waxing:
            x0, x1 = (1 - 2 * f) * xw, xw
        else:
            x0, x1 = -xw, (2 * f - 1) * xw
        if x1 > x0:
            y = cy + dy
            pygame.draw.line(screen, lit, (int(cx + x0), y), (int(cx + x1), y))

    pygame.draw.circle(screen, (70, 60, 48), (cx, cy), r, max(2, r // 120))
