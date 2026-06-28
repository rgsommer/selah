"""A subtle 'new photo just arrived' hint.

Instead of a full-width 'New photo from ...' toast, a small glyph is drawn
beside the clock for a short window after a new photo lands:
  * email from an approved sender -> 🤗 (a warm hug)
  * anything else                 -> 👀 (a glance)

The default pygame font can't render emoji, so the glyphs are drawn with
shapes (same approach as the weather icons).
"""

import time

import pygame

_last_seen = 0.0          # monotonic timestamp of the most recent new photo
_last_kind = "other"      # "email" -> hug, anything else -> eyes
_WINDOW = 90              # seconds the hint stays up (overridable via config)


def note_new_photo(kind="other"):
    """Mark that a new photo just arrived. kind='email' shows the hug glyph."""
    global _last_seen, _last_kind
    _last_seen = time.time()
    _last_kind = kind


def is_active(config=None):
    """True while the hint should still be shown."""
    window = (config or {}).get("new_photo_hint_seconds", _WINDOW)
    return _last_seen > 0 and (time.time() - _last_seen) < window


def current_kind():
    return _last_kind


def draw_glyph(target, x, cy, h, kind):
    """Draw the hint glyph for `kind` at (x, cy); returns x just past it."""
    if kind == "email":
        return draw_hug(target, x, cy, h)
    return draw_eyes(target, x, cy, h)


def draw_eyes(target, x, cy, h):
    """Draw the 👀 glyph centered vertically on `cy`, starting at `x`."""
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


def draw_hug(target, x, cy, h):
    """Draw the 🤗 glyph: a warm round face with two open hands beside it."""
    try:
        r = max(6, h // 3)
        cx = x + r
        face = (255, 205, 80)
        dark = (90, 60, 20)
        hands = (255, 224, 178)

        # Two open hands peeking from the lower sides (drawn first, behind face).
        hr = max(3, r // 2)
        pygame.draw.circle(target, hands, (cx - r + 1, cy + r // 2), hr)
        pygame.draw.circle(target, hands, (cx + r - 1, cy + r // 2), hr)

        # Face.
        pygame.draw.circle(target, face, (cx, cy), r)

        # Happy closed eyes: two short upward arcs (^ ^).
        ew = max(2, r // 2)
        ey = cy - r // 4
        for sx in (cx - r // 2, cx + r // 2):
            pygame.draw.arc(target, dark,
                            (sx - ew // 2, ey - ew // 2, ew, ew),
                            0.4, 2.74, max(2, r // 8))

        # Smile: lower arc.
        mw = r
        pygame.draw.arc(target, dark,
                        (cx - mw // 2, cy - r // 6, mw, r), 3.49, 6.06, max(2, r // 7))

        return cx + r + hr
    except Exception:
        return x
