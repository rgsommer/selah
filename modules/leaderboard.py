"""Contributor leaderboard - tracks photo submissions per sender."""

import json
import pygame
from modules.logger import log_error

LEADERBOARD_FILE = "leaderboard.json"


def update_leaderboard(sender, count=1):
    """Add submission count for a sender."""
    try:
        data = _load_leaderboard()
        # Prefer an explicit per-email alias, else the From display name.
        try:
            from modules.sender_aliases import alias_for
            name = alias_for(sender)
        except Exception:
            name = None
        if not name:
            name = sender.split("<")[0].strip().strip('"').strip("'")
        if not name:
            name = sender
        data[name] = data.get(name, 0) + count
        _save_leaderboard(data)
    except Exception as e:
        log_error(f"Leaderboard update failed: {e}")


def show_leaderboard(screens, config):
    """Display leaderboard overlay on screen. Press ESC or F3 to close."""
    screen = screens.get("landscape") or screens.get("portrait")
    if not screen:
        return

    try:
        data = _load_leaderboard()
        screen_w, screen_h = screen.get_size()
        font_size = max(24, screen_w // 35)
        font = pygame.font.Font(None, font_size)
        title_font = pygame.font.Font(None, font_size + 14)

        # Sort by count descending
        sorted_entries = sorted(data.items(), key=lambda x: x[1], reverse=True)

        running = True
        clock = pygame.time.Clock()

        while running:
            screen.fill((30, 20, 40))

            # Title
            title = title_font.render("Contributor Leaderboard (F3)", True, (255, 200, 100))
            title_rect = title.get_rect(centerx=screen_w // 2, top=15)
            screen.blit(title, title_rect)

            if not sorted_entries:
                msg = font.render("No contributions yet!", True, (200, 200, 200))
                msg_rect = msg.get_rect(centerx=screen_w // 2, top=80)
                screen.blit(msg, msg_rect)
            else:
                y = 70
                for rank, (name, count) in enumerate(sorted_entries[:15], 1):
                    # Medal colors for top 3
                    if rank == 1:
                        color = (255, 215, 0)   # Gold
                        prefix = "1st"
                    elif rank == 2:
                        color = (192, 192, 192)  # Silver
                        prefix = "2nd"
                    elif rank == 3:
                        color = (205, 127, 50)   # Bronze
                        prefix = "3rd"
                    else:
                        color = (200, 200, 200)
                        prefix = f"{rank}th"

                    # Truncate name
                    display_name = name[:25] + "..." if len(name) > 25 else name
                    line = f"  {prefix}  {display_name} — {count} photo{'s' if count != 1 else ''}"
                    text = font.render(line, True, color)
                    screen.blit(text, (40, y))
                    y += font_size + 10

            # Footer
            footer = font.render("Press ESC or F3 to close", True, (120, 120, 120))
            footer_rect = footer.get_rect(centerx=screen_w // 2, bottom=screen_h - 15)
            screen.blit(footer, footer_rect)

            try:
                pygame.display.flip()
            except Exception:
                pass

            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False
                elif event.type == pygame.KEYDOWN:
                    if event.key in (pygame.K_ESCAPE, pygame.K_F3):
                        running = False

            clock.tick(30)

    except Exception as e:
        log_error(f"Leaderboard display error: {e}")


def _load_leaderboard():
    try:
        with open(LEADERBOARD_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_leaderboard(data):
    try:
        with open(LEADERBOARD_FILE, "w") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        log_error(f"Failed to save leaderboard: {e}")
