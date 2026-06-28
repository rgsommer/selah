"""Subtle on-screen badge for pending sender approvals.

Instead of a toast that takes over a screen, a small unobtrusive chip in the
corner of the landscape screen shows how many senders are waiting, and that
F5 approves them all.
"""

import pygame

from modules.logger import log_error


def show_pending_badge(screens, config):
    if not config.get("pending_badge_enabled", True):
        return
    try:
        from modules.email_handler import count_pending
        n = count_pending()
    except Exception:
        n = 0
    if n <= 0:
        return

    # Prefer a landscape screen (don't clutter a portrait one); else any.
    screen = None
    for k, s in screens.items():
        if k.startswith("landscape"):
            screen = s
            break
    if screen is None:
        screen = next(iter(screens.values()), None)
    if screen is not None:
        _draw(screen, n)


def _draw(screen, n):
    try:
        w, h = screen.get_size()
        font = pygame.font.Font(None, max(20, w // 60))
        label = f"{n} pending  ·  F5 to approve all"
        text = font.render(label, True, (255, 232, 160))
        pad = 8
        tw, th = text.get_size()
        bw, bh = tw + pad * 2 + 18, th + pad * 2
        bx, by = w - bw - 16, h - bh - 16  # bottom-right, inset

        chip = pygame.Surface((bw, bh), pygame.SRCALPHA)
        chip.fill((40, 30, 12, 190))
        screen.blit(chip, (bx, by))
        pygame.draw.circle(screen, (255, 170, 60), (bx + pad + 5, by + bh // 2), 5)
        screen.blit(text, (bx + pad + 18, by + pad))
        try:
            pygame.display.flip()
        except Exception:
            pass
    except Exception as e:
        log_error(f"Pending badge failed: {e}")
