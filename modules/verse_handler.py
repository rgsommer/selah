"""Daily Bible verse display - YouVersion scrape with local fallback."""

import datetime
import json
import pygame
from modules.logger import log_error

_last_verse_date = None
_cached_verse = None


def show_verse_if_scheduled(screens, config):
    """Show the Verse of the Day at the top of each hour (on the hour) for 30 seconds."""
    global _last_verse_date, _cached_verse

    now = datetime.datetime.now()
    # Show verse at the top of each hour (minute 0, first 30 seconds)
    if now.minute != 0 or now.second > 30:
        return

    today = now.date()
    if _last_verse_date != today:
        _cached_verse = _get_verse_of_the_day(today, config)
        _last_verse_date = today

    if _cached_verse:
        for screen in screens.values():
            _render_verse(screen, _cached_verse)


def _get_verse_of_the_day(today, config):
    """Get verse of the day from YouVersion API or local fallback."""
    verse = _try_youversion()
    if not verse:
        verse = _try_local_fallback(today)
    if not verse:
        verse = {"reference": "Psalm 46:10", "text": "Be still, and know that I am God."}
    return verse


def _try_youversion():
    """Try to scrape verse of the day from YouVersion."""
    try:
        import requests
        from bs4 import BeautifulSoup
        url = "https://www.bible.com/verse-of-the-day"
        response = requests.get(url, timeout=10, headers={
            "User-Agent": "Mozilla/5.0 (compatible; SelahDisplay/1.0)"
        })
        if response.status_code == 200:
            soup = BeautifulSoup(response.text, "html.parser")
            # Try to find verse text and reference
            verse_elem = soup.find("p", class_=lambda c: c and "verse" in c.lower()) if soup else None
            ref_elem = soup.find("a", class_=lambda c: c and "ref" in c.lower()) if soup else None
            if verse_elem:
                return {
                    "reference": ref_elem.get_text(strip=True) if ref_elem else "Verse of the Day",
                    "text": verse_elem.get_text(strip=True)
                }
    except Exception as e:
        log_error(f"YouVersion fetch failed: {e}")
    return None


def _try_local_fallback(today):
    """Load verse from local verses.json file."""
    try:
        with open("verses.json", "r") as f:
            verses = json.load(f)
        today_str = today.isoformat()
        for verse in verses:
            if verse.get("date") == today_str:
                return {
                    "reference": verse.get("reference", verse.get("verse", "")),
                    "text": verse.get("text", verse.get("verse", ""))
                }
        # If no date match, cycle through verses by day of year
        if verses:
            idx = today.timetuple().tm_yday % len(verses)
            v = verses[idx]
            return {
                "reference": v.get("reference", v.get("verse", "")),
                "text": v.get("text", v.get("verse", ""))
            }
    except FileNotFoundError:
        pass
    except Exception as e:
        log_error(f"Local verse fallback failed: {e}")
    return None


def _render_verse(screen, verse):
    """Render verse text centered on screen with semi-transparent background."""
    try:
        screen_w, screen_h = screen.get_size()
        ref_font_size = max(30, screen_w // 25)
        text_font_size = max(24, screen_w // 35)

        ref_font = pygame.font.Font(None, ref_font_size)
        text_font = pygame.font.Font(None, text_font_size)

        reference = verse.get("reference", "")
        text = verse.get("text", "")

        # Word-wrap the verse text
        words = text.split()
        lines = []
        current_line = ""
        max_width = screen_w - 100
        for word in words:
            test_line = f"{current_line} {word}".strip()
            if text_font.size(test_line)[0] <= max_width:
                current_line = test_line
            else:
                if current_line:
                    lines.append(current_line)
                current_line = word
        if current_line:
            lines.append(current_line)

        # Calculate total height
        line_height = text_font.get_linesize()
        ref_height = ref_font.get_linesize()
        total_height = ref_height + 10 + (line_height * len(lines)) + 40

        # Background box
        box_y = (screen_h - total_height) // 2
        bg_surface = pygame.Surface((screen_w - 60, total_height), pygame.SRCALPHA)
        bg_surface.fill((0, 0, 0, 180))
        screen.blit(bg_surface, (30, box_y))

        # Render reference
        ref_surface = ref_font.render(reference, True, (255, 215, 0))  # Gold
        ref_rect = ref_surface.get_rect(centerx=screen_w // 2, top=box_y + 15)
        screen.blit(ref_surface, ref_rect)

        # Render verse lines
        y = box_y + ref_height + 25
        for line in lines:
            line_surface = text_font.render(line, True, (255, 255, 255))
            line_rect = line_surface.get_rect(centerx=screen_w // 2, top=y)
            screen.blit(line_surface, line_rect)
            y += line_height

        try:
            pygame.display.flip()
        except Exception:
            pass
    except Exception as e:
        log_error(f"Verse render failed: {e}")
