"""Google Calendar event display with scrolling feed."""

import datetime
import json
import pygame
from modules.logger import log_error

_last_calendar_check = None
_cached_events = []


def _parse_hhmm(value):
    """Parse 'HH:MM' into (hour, minute), or None if invalid."""
    try:
        t = datetime.datetime.strptime(str(value), "%H:%M")
        return t.hour, t.minute
    except Exception:
        return None


def show_calendar_if_scheduled(screens, config):
    """Show the daily agenda from Google Calendar.

    Two modes, chosen by ``calendar_duration_minutes``:
      * > 0 : the agenda runs as a window starting at ``calendar_start_time``
              for that many minutes, then stops for the day. (e.g. start 06:00,
              duration 120 -> agenda shows 06:00-08:00.)
      * 0   : legacy behavior — a brief agenda twice an hour, all day.
    """
    now = datetime.datetime.now()
    duration = int(config.get("calendar_duration_minutes", 0) or 0)

    if duration > 0:
        start = _parse_hhmm(config.get("calendar_start_time", "06:00"))
        if start is None:
            return
        start_dt = now.replace(hour=start[0], minute=start[1], second=0, microsecond=0)
        end_dt = start_dt + datetime.timedelta(minutes=duration)
        if not (start_dt <= now < end_dt):
            return
    else:
        # Legacy: a quick pass at :15 and :45.
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
        # Today + tomorrow only, in the display's local timezone.
        start = datetime.datetime.now().astimezone().replace(
            hour=0, minute=0, second=0, microsecond=0)
        end = start + datetime.timedelta(days=2)

        events_result = service.events().list(
            calendarId=config.get("google_calendar_id", "primary"),
            timeMin=start.isoformat(),
            timeMax=end.isoformat(),
            maxResults=25,
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
        # Keep only today and tomorrow.
        today = datetime.date.today()
        tomorrow = today + datetime.timedelta(days=1)
        upcoming = []
        for event in events:
            try:
                event_date = datetime.datetime.fromisoformat(
                    event.get("start", event.get("date", ""))[:10]
                ).date()
                if today <= event_date <= tomorrow:
                    upcoming.append(event)
            except Exception:
                upcoming.append(event)  # include if we can't parse the date
        return upcoming
    except FileNotFoundError:
        return []
    except Exception as e:
        log_error(f"Local calendar load failed: {e}")
        return []


def _event_when(start_str):
    """Return (date, time_label) for an event start; 'All day' for date-only."""
    try:
        s = str(start_str)
        if "T" in s:
            dt = datetime.datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone()
            try:
                return dt.date(), dt.strftime("%-I:%M %p")
            except Exception:
                return dt.date(), dt.strftime("%H:%M")
        return datetime.date.fromisoformat(s[:10]), "All day"
    except Exception:
        return None, ""


def _render_scrolling_calendar(screen, events, config):
    """Render a Today / Tomorrow agenda as a right-side panel."""
    try:
        screen_w, screen_h = screen.get_size()
        today = datetime.date.today()
        tomorrow = today + datetime.timedelta(days=1)

        grouped = {today: [], tomorrow: []}
        for e in events:
            d, tl = _event_when(e.get("start", ""))
            if d in grouped:
                grouped[d].append((tl, e.get("summary", "Untitled")))

        font_size = max(24, screen_w // 38)
        head_font = pygame.font.Font(None, font_size + 6)
        font = pygame.font.Font(None, font_size)
        small = pygame.font.Font(None, max(20, font_size - 6))

        # Flatten into drawable lines.
        lines = []  # (kind, payload)
        for title, d in (("Today", today), ("Tomorrow", tomorrow)):
            lines.append(("header", title))
            evs = grouped.get(d, [])
            if not evs:
                lines.append(("empty", "— nothing scheduled"))
            else:
                for tl, summary in evs:
                    lines.append(("event", (tl, summary)))

        line_h = font.get_linesize() + 8
        panel_w = min(screen_w // 3, 460)
        panel_h = min(len(lines) * line_h + 60, screen_h - 40)
        x = screen_w - panel_w - 16
        y = (screen_h - panel_h) // 2

        bg = pygame.Surface((panel_w, panel_h), pygame.SRCALPHA)
        bg.fill((0, 0, 40, 190))
        screen.blit(bg, (x, y))

        cy = y + 14
        time_col = max(96, panel_w // 4)
        for kind, payload in lines:
            if cy + line_h > y + panel_h - 8:
                break
            if kind == "header":
                surf = head_font.render(payload, True, (120, 200, 255))
                screen.blit(surf, (x + 14, cy))
                cy += head_font.get_linesize() + 4
            elif kind == "empty":
                screen.blit(small.render(payload, True, (150, 150, 160)), (x + 24, cy))
                cy += line_h
            else:
                tl, summary = payload
                max_chars = max(8, (panel_w - time_col) // max(1, font_size // 2))
                if len(summary) > max_chars:
                    summary = summary[:max_chars - 1] + "…"
                screen.blit(small.render(tl, True, (210, 210, 140)), (x + 24, cy + 2))
                screen.blit(font.render(summary, True, (255, 255, 255)), (x + 24 + time_col, cy))
                cy += line_h

        try:
            pygame.display.flip()
        except Exception:
            pass
    except Exception as e:
        log_error(f"Calendar render failed: {e}")
