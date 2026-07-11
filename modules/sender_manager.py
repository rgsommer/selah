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
        scroll = 0
        adding = False
        add_buffer = ""
        running = True
        clock = pygame.time.Clock()
        max_rows = 1

        while running:
            screen.fill((20, 30, 20))

            # Title
            title = title_font.render("Sender Manager (F2)", True, (100, 255, 100))
            screen.blit(title, (20, 10))

            instructions = font.render(
                "Up/Down  PgUp/PgDn  Home/End   A=Add  D=Delete  ESC=Close",
                True, (150, 150, 150)
            )
            screen.blit(instructions, (20, 15 + title_font.get_linesize()))

            list_top = 60 + title_font.get_linesize()
            row_h = font_size + 10
            # Reserve space at the bottom for the add-email prompt when active.
            bottom_reserve = (row_h * 3 + 20) if adding else 10
            avail = max(row_h, screen_h - list_top - bottom_reserve)
            max_rows = max(1, avail // row_h)

            if not senders:
                msg = font.render("No approved senders (all senders allowed)", True, (200, 200, 100))
                screen.blit(msg, (20, list_top))
            else:
                # Keep the selected row inside the visible window.
                if selected < scroll:
                    scroll = selected
                elif selected >= scroll + max_rows:
                    scroll = selected - max_rows + 1
                scroll = max(0, min(scroll, max(0, len(senders) - max_rows)))

                y = list_top
                for i in range(scroll, min(scroll + max_rows, len(senders))):
                    if i == selected:
                        highlight = pygame.Surface((screen_w - 20, font_size + 8), pygame.SRCALPHA)
                        highlight.fill((40, 80, 40, 150))
                        screen.blit(highlight, (10, y - 3))
                    color = (255, 255, 255) if i == selected else (200, 200, 200)
                    text = font.render(f"  {senders[i]}", True, color)
                    screen.blit(text, (20, y))
                    y += row_h

                # "more above / below" hints + position counter.
                counter = font.render(f"{selected + 1}/{len(senders)}", True, (150, 150, 150))
                screen.blit(counter, (screen_w - counter.get_width() - 20,
                                      15 + title_font.get_linesize()))
                if scroll > 0:
                    up = font.render("▲ more", True, (120, 200, 120))
                    screen.blit(up, (screen_w - up.get_width() - 20, list_top - row_h + 2))
                if scroll + max_rows < len(senders):
                    dn = font.render("▼ more", True, (120, 200, 120))
                    screen.blit(dn, (screen_w - dn.get_width() - 20, list_top + max_rows * row_h - 2))

            # Add mode — anchored at the bottom, independent of the scrolled list.
            if adding:
                ay = screen_h - bottom_reserve + 10
                prompt = font.render("Enter email address:", True, (255, 255, 100))
                screen.blit(prompt, (20, ay))
                ay += font_size + 5
                input_text = font.render(f"  {add_buffer}_", True, (255, 255, 255))
                screen.blit(input_text, (20, ay))

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
                        elif event.key == pygame.K_PAGEDOWN and senders:
                            selected = min(selected + max_rows, len(senders) - 1)
                        elif event.key == pygame.K_PAGEUP and senders:
                            selected = max(selected - max_rows, 0)
                        elif event.key == pygame.K_HOME and senders:
                            selected = 0
                        elif event.key == pygame.K_END and senders:
                            selected = len(senders) - 1
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
