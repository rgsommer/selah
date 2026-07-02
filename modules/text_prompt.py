"""A small modal text entry (edit a caption, etc.). Returns the edited string
on Enter, or None on Esc. Blocks like the other F-key modals."""

import pygame

from modules.logger import log_error


def prompt_text(screen, title, initial="", max_len=120):
    """Block for a line of text, pre-filled with `initial`. Returns the string,
    or None if cancelled."""
    try:
        text = initial or ""
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
                    return text.strip()
                if event.key == pygame.K_BACKSPACE:
                    text = text[:-1]
                elif event.unicode and event.unicode.isprintable() and len(text) < max_len:
                    text += event.unicode
            _draw(screen, title, text)
            clock.tick(30)
    except Exception as e:
        log_error(f"Text prompt failed: {e}")
        return None


def _draw(screen, title, text):
    w, h = screen.get_size()
    title_font = pygame.font.Font(None, max(30, w // 30))
    text_font = pygame.font.Font(None, max(30, w // 26))
    hint_font = pygame.font.Font(None, max(22, w // 48))

    pw = min(int(w * 0.8), 900)
    ph = min(int(h * 0.5), 280)
    x, y = (w - pw) // 2, (h - ph) // 2

    overlay = pygame.Surface((w, h), pygame.SRCALPHA)
    overlay.fill((0, 0, 0, 190))
    panel = pygame.Surface((pw, ph), pygame.SRCALPHA)
    panel.fill((24, 24, 34, 245))
    overlay.blit(panel, (x, y))

    t = title_font.render(title, True, (255, 210, 140))
    overlay.blit(t, t.get_rect(midtop=(w // 2, y + 24)))

    # The editable text, with a blinking-ish cursor and left-truncation so the
    # end (where you're typing) stays visible.
    shown = text
    box_w = pw - 60
    while shown and text_font.size(shown + "|")[0] > box_w:
        shown = shown[1:]
    d = text_font.render((shown + "|") if shown or True else "", True, (255, 255, 255))
    overlay.blit(d, d.get_rect(midleft=(x + 30, y + ph // 2)))

    hint = hint_font.render("Type to edit    Enter = save    Esc = cancel",
                            True, (150, 155, 170))
    overlay.blit(hint, hint.get_rect(midbottom=(w // 2, y + ph - 22)))

    screen.blit(overlay, (0, 0))
    pygame.display.flip()
