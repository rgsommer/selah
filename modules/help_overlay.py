"""On-screen help: lists the keyboard / touch controls.

Shown by pressing H (or ?). Modal like the other F-key screens — it draws a
centred panel and waits for any key / tap to dismiss.
"""

import pygame

from modules.logger import log_error

_KEYS = [
    ("← / →", "Previous / next photo"),
    ("↑ / ↓", "Previous / next photo"),
    ("Space", "Play / pause"),
    ("F1", "Settings"),
    ("F2", "Manage senders"),
    ("F3", "Leaderboard"),
    ("F4", "Quiz mode"),
    ("F5", "Approve all pending senders"),
    ("F6", "Agenda / 5-day forecast panel"),
    ("F7", "Show today's 'On this day' memories"),
    ("F8", "Feature new photos from the last few days"),
    ("F9", "Displays off (+1 hr/press, up to 6; nav wakes)"),
    ("F10", "Edit a photo's caption — pick its number"),
    ("Del", "Delete a photo — pick its number, then code"),
    ("H  or  ?", "This help"),
    ("Esc", "Quit"),
    ("Tap / swipe", "Previous / next photo"),
]


def show_help(screen, config=None):
    """Draw the controls list and block until a key is pressed or screen tapped."""
    try:
        w, h = screen.get_size()
        title_font = pygame.font.Font(None, max(34, w // 26))
        key_font = pygame.font.Font(None, max(26, w // 40))
        desc_font = pygame.font.Font(None, max(26, w // 42))

        line_h = key_font.get_linesize() + 12
        panel_w = min(int(w * 0.8), 820)
        panel_h = min(int(h * 0.9), line_h * (len(_KEYS) + 3) + 40)
        x = (w - panel_w) // 2
        y = (h - panel_h) // 2

        overlay = pygame.Surface((w, h), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 180))                 # dim the slideshow behind
        panel = pygame.Surface((panel_w, panel_h), pygame.SRCALPHA)
        panel.fill((18, 20, 32, 240))
        overlay.blit(panel, (x, y))

        title = title_font.render("Controls", True, (120, 200, 255))
        overlay.blit(title, (x + 30, y + 22))

        cy = y + 22 + title_font.get_linesize() + 10
        key_col = x + 30
        desc_col = x + 30 + max(180, panel_w // 3)
        for key, desc in _KEYS:
            if cy + line_h > y + panel_h - 16:
                break
            overlay.blit(key_font.render(key, True, (255, 224, 140)), (key_col, cy))
            overlay.blit(desc_font.render(desc, True, (235, 235, 240)), (desc_col, cy))
            cy += line_h

        hint = desc_font.render("Press any key to close", True, (150, 155, 170))
        overlay.blit(hint, (x + 30, y + panel_h - hint.get_height() - 16))

        screen.blit(overlay, (0, 0))
        pygame.display.flip()

        # Block until a key / tap (drain any queued events first).
        pygame.event.clear()
        waiting = True
        clock = pygame.time.Clock()
        while waiting:
            for event in pygame.event.get():
                if event.type in (pygame.KEYDOWN, pygame.MOUSEBUTTONDOWN,
                                  pygame.FINGERDOWN, pygame.QUIT):
                    waiting = False
                    break
            clock.tick(30)
    except Exception as e:
        log_error(f"Help overlay failed: {e}")
