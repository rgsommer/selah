"""'Coming up' overlay — the soonest upcoming family birthday.

Shows a brief banner periodically (e.g. "Mom's birthday in 3 days") using the
contacts list, so the family gets a gentle heads-up to send greetings early.
"""

import time
import datetime

import pygame

from modules.logger import log_error


def _next_birthday(within_days=30):
    try:
        from modules.contacts import load_contacts, derive_name
    except Exception:
        return None
    today = datetime.date.today()
    best = None
    for c in load_contacts():
        b = str(c.get("birthday", "")).strip()
        if len(b) < 5:
            continue
        mmdd = b[-5:]  # MM-DD
        try:
            mo, da = int(mmdd[:2]), int(mmdd[3:5])
            nxt = datetime.date(today.year, mo, da)
        except Exception:
            continue
        if nxt < today:
            try:
                nxt = datetime.date(today.year + 1, mo, da)
            except ValueError:
                continue
        days = (nxt - today).days
        if days <= within_days and (best is None or days < best[0]):
            best = (days, c.get("name") or derive_name(c.get("email", "")))
    return best


def show_coming_up_if_scheduled(screens, config):
    if not config.get("coming_up_enabled", False):
        return
    interval = max(60, int(config.get("coming_up_interval_minutes", 20)) * 60)
    show_secs = int(config.get("coming_up_seconds", 15))
    if (time.time() % interval) >= show_secs:
        return

    ev = _next_birthday()
    if not ev:
        return
    days, name = ev
    when = "today!" if days == 0 else ("tomorrow" if days == 1 else f"in {days} days")
    text = f"\U0001F382  {name}'s birthday {when}"
    for screen in screens.values():
        _render(screen, text)


def _render(screen, text):
    try:
        w, h = screen.get_size()
        font = pygame.font.Font(None, max(24, w // 38))
        surf = font.render(text, True, (255, 238, 200))
        bar_h = surf.get_height() + 18
        y = int(h * 0.72)
        bg = pygame.Surface((w, bar_h), pygame.SRCALPHA)
        bg.fill((40, 25, 55, 185))
        screen.blit(bg, (0, y))
        screen.blit(surf, surf.get_rect(center=(w // 2, y + bar_h // 2)))
        try:
            pygame.display.flip()
        except Exception:
            pass
    except Exception as e:
        log_error(f"Coming-up render failed: {e}")
