"""A subtle 'new photo just arrived' hint.

Instead of a full-width 'New photo from ...' toast, a small pair of eyes (👀)
is drawn beside the clock for a short window after a photo lands from an
approved sender. The default pygame font can't render emoji, so the eyes are
drawn with shapes (same approach as the weather icons).
"""

import time

import pygame

_last_seen = 0.0          # monotonic timestamp of the most recent new photo
_WINDOW = 90              # seconds the hint stays up (overridable via config)


def note_new_photo():
    """Mark that a new photo just arrived (call when one is displayed)."""
    global _last_seen
    _last_seen = time.time()


def is_active(config=None):
    """True while the hint should still be shown."""
    window = (config or {}).get("new_photo_hint_seconds", _WINDOW)
    return _last_seen > 0 and (time.time() - _last_seen) < window


def eyes_width(h):
    """Pixel width the eyes glyph will occupy for a given band height `h`."""
    r = max(4, h // 6)
    return 4 * r + r // 2  # two eyes (2r each) + small gap


def draw_eyes(target, x, cy, h):
    """Draw the 👀 glyph centered vertically on `cy`, starting at `x`.

    Returns the x just past the glyph.
    """
    try:
        r = max(4, h // 6)
        gap = r // 2
        white = (240, 240, 245)
        dark = (45, 45, 60)
        for i in (0, 1):
            ex = x + r + i * (2 * r + gap)
            pygame.draw.circle(target, white, (ex, cy), r)            # eye white
            pygame.draw.circle(target, dark, (ex + r // 3, cy + r // 4),
                               max(2, r // 2))                        # pupil (glancing down)
        return x + 4 * r + gap
    except Exception:
        return x
