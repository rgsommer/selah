"""F2 sender approval manager - approve/reject email contributors."""

import json
import pygame
from modules.logger import log_error

APPROVED_SENDERS_FILE = "approved_senders.json"


def show_sender_manager(screen, config):
    """Display sender management interface.

    Shows approved senders, allows adding/removing.
    Press ESC or F2 to close.
    """
    if not screen:
        return

    try:
        senders = _load_senders()
        screen_w, screen_h = screen.get_size()
        font_size = max(22, screen_w // 40)
        font = pygame.font.Font(None, font_size)
        title_font = pygame.font.Font(None, font_size + 10)

        selected = 0
        adding = False
        add_buffer = ""
        running = True
        clock = pygame.time.Clock()

        while running:
            screen.fill((20, 30, 20))

            # Title
            title = title_font.render("Sender Manager (F2)", True, (100, 255, 100))
            screen.blit(title, (20, 10))

            instructions = font.render(
                "Up/Down=Navigate  A=Add  D=Delete  ESC=Close",
                True, (150, 150, 150)
            )
            screen.blit(instructions, (20, 15 + title_font.get_linesize()))

            y = 60 + title_font.get_linesize()

            if not senders:
                msg = font.render("No approved senders (all senders allowed)", True, (200, 200, 100))
                screen.blit(msg, (20, y))
                y += font_size + 10

            for i, sender in enumerate(senders):
                if i == selected:
                    highlight = pygame.Surface((screen_w - 20, font_size + 8), pygame.SRCALPHA)
                    highlight.fill((40, 80, 40, 150))
                    screen.blit(highlight, (10, y - 3))

                color = (255, 255, 255) if i == selected else (200, 200, 200)
                text = font.render(f"  {sender}", True, color)
                screen.blit(text, (20, y))
                y += font_size + 10

            # Add mode
            if adding:
                y += 20
                prompt = font.render("Enter email address:", True, (255, 255, 100))
                screen.blit(prompt, (20, y))
                y += font_size + 5
                input_text = font.render(f"  {add_buffer}_", True, (255, 255, 255))
                screen.blit(input_text, (20, y))

            try:
                pygame.display.flip()
            except Exception:
                pass

            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False
                elif event.type == pygame.KEYDOWN:
                    if adding:
                        if event.key == pygame.K_RETURN and add_buffer.strip():
                            senders.append(add_buffer.strip())
                            _save_senders(senders)
                            add_buffer = ""
                            adding = False
                        elif event.key == pygame.K_ESCAPE:
                            adding = False
                            add_buffer = ""
                        elif event.key == pygame.K_BACKSPACE:
                            add_buffer = add_buffer[:-1]
                        elif event.unicode and event.unicode.isprintable():
                            add_buffer += event.unicode
                    else:
                        if event.key in (pygame.K_ESCAPE, pygame.K_F2):
                            running = False
                        elif event.key == pygame.K_DOWN and senders:
                            selected = min(selected + 1, len(senders) - 1)
                        elif event.key == pygame.K_UP and senders:
                            selected = max(selected - 1, 0)
                        elif event.key == pygame.K_a:
                            adding = True
                            add_buffer = ""
                        elif event.key == pygame.K_d and senders:
                            if 0 <= selected < len(senders):
                                senders.pop(selected)
                                _save_senders(senders)
                                selected = max(0, selected - 1)

            clock.tick(30)

    except Exception as e:
        log_error(f"Sender manager error: {e}")


def _load_senders():
    """Load approved senders from JSON file."""
    try:
        with open(APPROVED_SENDERS_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return []


def _save_senders(senders):
    """Save approved senders to JSON file."""
    try:
        with open(APPROVED_SENDERS_FILE, "w") as f:
            json.dump(senders, f, indent=2)
    except Exception as e:
        log_error(f"Failed to save senders: {e}")
