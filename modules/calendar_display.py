"""Google Calendar event display with scrolling feed."""

import datetime
import json
import pygame
from modules.logger import log_error

_last_calendar_check = None
_cached_events = []


def show_calendar_if_scheduled(screens, config):
    """Show calendar events at scheduled times (every 30 minutes, at :15 and :45)."""
    now = datetime.datetime.now()
    if now.minute not in (15, 45) or now.second > 30:
        return

    events = _get_calendar_events(config)
    if events:
        for screen in screens.values():
            _render_scrolling_calendar(screen, events, config)


def _get_calendar_events(config):
    """Fetch calendar events from Google Calendar API or local file."""
    global _last_calendar_check, _cached_events

    now = datetime.datetime.now()
    # Cache for 10 minutes
    if _last_calendar_check and (now - _last_calendar_check).seconds < 600:
        return _cached_events

    events = _try_google_calendar(config)
    if not events:
        events = _try_local_calendar()

    _cached_events = events
    _last_calendar_check = now
    return events


def _try_google_calendar(config):
    """Try to fetch events from Google Calendar API."""
    try:
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from googleapiclient.discovery import build
        import os

        creds = None
        if os.path.exists("token.json"):
            creds = Credentials.from_authorized_user_file("token.json")

        if not creds or not creds.valid:
            return None

        service = build("calendar", "v3", credentials=creds)
        now_str = datetime.datetime.utcnow().isoformat() + "Z"
        end = (datetime.datetime.utcnow() + datetime.timedelta(days=7)).isoformat() + "Z"

        events_result = service.events().list(
            calendarId="primary",
            timeMin=now_str,
            timeMax=end,
            maxResults=20,
            singleEvents=True,
            orderBy="startTime"
        ).execute()

        events = []
        for event in events_result.get("items", []):
            start = event["start"].get("dateTime", event["start"].get("date"))
            events.append({
                "summary": event.get("summary", "Untitled"),
                "start": start,
                "location": event.get("location", "")
            })
        return events
    except Exception as e:
        log_error(f"Google Calendar fetch failed: {e}")
        return None


def _try_local_calendar():
    """Load events from local calendar_events.json."""
    try:
        with open("calendar_events.json", "r") as f:
            events = json.load(f)
        # Filter to upcoming events
        today = datetime.date.today()
        upcoming = []
        for event in events:
            try:
                event_date = datetime.datetime.fromisoformat(
                    event.get("start", event.get("date", ""))
                ).date()
                if event_date >= today:
                    upcoming.append(event)
            except Exception:
                upcoming.append(event)  # Include if we can't parse date
        return upcoming
    except FileNotFoundError:
        return []
    except Exception as e:
        log_error(f"Local calendar load failed: {e}")
        return []


def _render_scrolling_calendar(screen, events, config):
    """Render calendar events as a scrolling feed overlay."""
    try:
        screen_w, screen_h = screen.get_size()
        font_size = max(24, screen_w // 35)
        font = pygame.font.Font(None, font_size)
        small_font = pygame.font.Font(None, max(20, font_size - 6))

        # Build event text lines
        lines = []
        for event in events[:10]:  # Max 10 events
            summary = event.get("summary", "Untitled")
            start = event.get("start", "")
            # Format date nicely
            try:
                dt = datetime.datetime.fromisoformat(start.replace("Z", "+00:00"))
                date_str = dt.strftime("%a %b %d, %I:%M %p")
            except Exception:
                date_str = start
            lines.append((summary, date_str))

        if not lines:
            return

        line_height = font.get_linesize() + small_font.get_linesize() + 10
        total_height = min(len(lines) * line_height + 40, screen_h // 2)

        # Semi-transparent sidebar on the right
        sidebar_w = min(screen_w // 3, 400)
        bg_surface = pygame.Surface((sidebar_w, total_height), pygame.SRCALPHA)
        bg_surface.fill((0, 0, 50, 180))
        x_pos = screen_w - sidebar_w - 10
        y_pos = (screen_h - total_height) // 2
        screen.blit(bg_surface, (x_pos, y_pos))

        # Header
        header = font.render("Upcoming Events", True, (100, 200, 255))
        screen.blit(header, (x_pos + 10, y_pos + 5))

        # Events
        y = y_pos + font.get_linesize() + 15
        for summary, date_str in lines:
            if y + line_height > y_pos + total_height:
                break
            # Truncate if too long
            max_chars = sidebar_w // (font_size // 2)
            if len(summary) > max_chars:
                summary = summary[:max_chars - 3] + "..."

            title_surf = font.render(summary, True, (255, 255, 255))
            date_surf = small_font.render(date_str, True, (180, 180, 180))
            screen.blit(title_surf, (x_pos + 10, y))
            screen.blit(date_surf, (x_pos + 10, y + font.get_linesize()))
            y += line_height

        try:
            pygame.display.flip()
        except Exception:
            pass
    except Exception as e:
        log_error(f"Calendar render failed: {e}")
