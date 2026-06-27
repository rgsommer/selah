"""Night mode: analog clock with nightly quote displayed during off-hours."""

import datetime
import json
import math
import pygame
from modules.logger import log_error

_todays_quote = None
_quote_date = None

# Default quotes if no file is available
DEFAULT_QUOTES = [
    "Be still, and know that I am God. - Psalm 46:10",
    "The Lord is my shepherd; I shall not want. - Psalm 23:1",
    "Trust in the Lord with all your heart. - Proverbs 3:5",
    "I can do all things through Christ who strengthens me. - Philippians 4:13",
    "For God so loved the world. - John 3:16",
    "The joy of the Lord is your strength. - Nehemiah 8:10",
    "Cast all your anxiety on Him because He cares for you. - 1 Peter 5:7",
    "Be strong and courageous. - Joshua 1:9",
    "His mercies are new every morning. - Lamentations 3:23",
    "Peace I leave with you; my peace I give you. - John 14:27",
]


def show_clock_with_quote(screen, config):
    """Display an analog clock with the nightly quote on the given screen."""
    global _todays_quote, _quote_date

    try:
        now = datetime.datetime.now()
        today = now.date()

        # Pick one quote per day
        if _quote_date != today:
            _todays_quote = _get_nightly_quote(today)
            _quote_date = today

        screen.fill((0, 0, 0))  # Black background
        screen_w, screen_h = screen.get_size()

        # Draw analog clock
        _draw_analog_clock(screen, now, screen_w, screen_h)

        # Draw digital time below clock
        _draw_digital_time(screen, now, screen_w, screen_h)

        # Draw quote at bottom
        if _todays_quote:
            _draw_quote(screen, _todays_quote, screen_w, screen_h)

        try:
            pygame.display.flip()
        except Exception:
            pass

    except Exception as e:
        log_error(f"Clock/quote display failed: {e}")


def _draw_analog_clock(screen, now, screen_w, screen_h):
    """Draw an analog clock face with hour, minute, and second hands."""
    cx = screen_w // 2
    cy = screen_h // 3  # Upper portion of screen
    radius = min(screen_w, screen_h) // 4

    # Clock face (circle)
    pygame.draw.circle(screen, (60, 60, 60), (cx, cy), radius, 2)

    # Hour markers
    for i in range(12):
        angle = math.radians(i * 30 - 90)
        inner = radius - 15
        outer = radius - 5
        x1 = cx + int(inner * math.cos(angle))
        y1 = cy + int(inner * math.sin(angle))
        x2 = cx + int(outer * math.cos(angle))
        y2 = cy + int(outer * math.sin(angle))
        width = 3 if i % 3 == 0 else 1
        pygame.draw.line(screen, (200, 200, 200), (x1, y1), (x2, y2), width)

    # Hour hand
    hour = now.hour % 12
    minute = now.minute
    hour_angle = math.radians((hour + minute / 60) * 30 - 90)
    hour_len = radius * 0.5
    hx = cx + int(hour_len * math.cos(hour_angle))
    hy = cy + int(hour_len * math.sin(hour_angle))
    pygame.draw.line(screen, (255, 255, 255), (cx, cy), (hx, hy), 4)

    # Minute hand
    min_angle = math.radians(minute * 6 - 90)
    min_len = radius * 0.7
    mx = cx + int(min_len * math.cos(min_angle))
    my = cy + int(min_len * math.sin(min_angle))
    pygame.draw.line(screen, (200, 200, 200), (cx, cy), (mx, my), 2)

    # Second hand
    sec_angle = math.radians(now.second * 6 - 90)
    sec_len = radius * 0.75
    sx = cx + int(sec_len * math.cos(sec_angle))
    sy = cy + int(sec_len * math.sin(sec_angle))
    pygame.draw.line(screen, (200, 50, 50), (cx, cy), (sx, sy), 1)

    # Center dot
    pygame.draw.circle(screen, (255, 255, 255), (cx, cy), 5)


def _draw_digital_time(screen, now, screen_w, screen_h):
    """Draw digital time below the analog clock."""
    font_size = max(40, screen_w // 15)
    font = pygame.font.Font(None, font_size)
    time_str = now.strftime("%I:%M %p")
    date_str = now.strftime("%A, %B %d")

    time_surface = font.render(time_str, True, (200, 200, 200))
    time_rect = time_surface.get_rect(centerx=screen_w // 2, top=screen_h // 2 + 20)
    screen.blit(time_surface, time_rect)

    date_font = pygame.font.Font(None, max(28, font_size // 2))
    date_surface = date_font.render(date_str, True, (150, 150, 150))
    date_rect = date_surface.get_rect(centerx=screen_w // 2, top=time_rect.bottom + 10)
    screen.blit(date_surface, date_rect)


def _draw_quote(screen, quote, screen_w, screen_h):
    """Draw the nightly quote at the bottom of the screen."""
    font_size = max(22, screen_w // 40)
    font = pygame.font.Font(None, font_size)

    # Word wrap
    words = quote.split()
    lines = []
    current_line = ""
    max_width = screen_w - 80
    for word in words:
        test = f"{current_line} {word}".strip()
        if font.size(test)[0] <= max_width:
            current_line = test
        else:
            if current_line:
                lines.append(current_line)
            current_line = word
    if current_line:
        lines.append(current_line)

    # Render from bottom up
    line_h = font.get_linesize()
    y = screen_h - 40 - (len(lines) * line_h)
    for line in lines:
        surface = font.render(line, True, (180, 180, 120))  # Warm tone
        rect = surface.get_rect(centerx=screen_w // 2, top=y)
        screen.blit(surface, rect)
        y += line_h


def _get_nightly_quote(today):
    """Get one quote for tonight. Uses quotes.json or defaults."""
    try:
        quotes = DEFAULT_QUOTES
        try:
            with open("quotes.json", "r") as f:
                loaded = json.load(f)
            if loaded:
                quotes = loaded
        except FileNotFoundError:
            pass

        # Pick quote by day of year
        idx = today.timetuple().tm_yday % len(quotes)
        q = quotes[idx]
        if isinstance(q, dict):
            return q.get("text", q.get("quote", str(q)))
        return str(q)
    except Exception as e:
        log_error(f"Quote loading failed: {e}")
        return "Be still, and know that I am God."
