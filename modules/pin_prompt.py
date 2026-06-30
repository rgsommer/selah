"""A small modal PIN entry, used to confirm destructive actions (delete).

Shows a centred box, captures digits (masked), and returns the entered string
on Enter, or None on Esc. Blocks until the user finishes — like the other
F-key modals.
"""

import pygame

from modules.logger import log_error


def prompt_pin(screen, title="Enter code", max_len=8):
    """Block for a PIN. Returns the entered string, or None if cancelled."""
    try:
        entered = ""
        clock = pygame.time.Clock()
        pygame.event.clear()
        while True:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    return None
                if event.type != pygame.KEYDOWN:
                    continue
                if event.key == pygame.K_ESCAPE:
                    return None
                if event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                    return entered
                if event.key == pygame.K_BACKSPACE:
                    entered = entered[:-1]
                elif event.unicode and event.unicode.isdigit() and len(entered) < max_len:
                    entered += event.unicode
            _draw(screen, title, entered)
            clock.tick(30)
    except Exception as e:
        log_error(f"PIN prompt failed: {e}")
        return None


def _draw(screen, title, entered):
    w, h = screen.get_size()
    title_font = pygame.font.Font(None, max(30, w // 28))
    dot_font = pygame.font.Font(None, max(40, w // 18))
    hint_font = pygame.font.Font(None, max(22, w // 48))

    pw = min(int(w * 0.6), 560)
    ph = min(int(h * 0.5), 260)
    x, y = (w - pw) // 2, (h - ph) // 2

    overlay = pygame.Surface((w, h), pygame.SRCALPHA)
    overlay.fill((0, 0, 0, 180))
    panel = pygame.Surface((pw, ph), pygame.SRCALPHA)
    panel.fill((24, 24, 34, 240))
    overlay.blit(panel, (x, y))

    t = title_font.render(title, True, (255, 210, 140))
    overlay.blit(t, t.get_rect(center=(w // 2, y + ph // 4)))

    dots = "•" * len(entered) if entered else "—"
    d = dot_font.render(dots, True, (255, 255, 255))
    overlay.blit(d, d.get_rect(center=(w // 2, y + ph // 2)))

    hint = hint_font.render("Enter = confirm    Esc = cancel", True, (150, 155, 170))
    overlay.blit(hint, hint.get_rect(center=(w // 2, y + ph - 30)))

    screen.blit(overlay, (0, 0))
    pygame.display.flip()
