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


def _calendar_times(config):
    """Scheduled agenda times: calendar_times list, or [calendar_start_time]."""
    times = config.get("calendar_times")
    if not times:
        single = (config.get("calendar_start_time") or "").strip()
        times = [single] if single else []
    elif isinstance(times, str):
        times = [times]
    return [t for t in (str(x).strip() for x in times) if _parse_hhmm(t) is not None]


def agenda_in_window(config):
    """True if the agenda should be on screen right now (per calendar_times /
    calendar_duration_minutes, or the legacy :15/:45 pass)."""
    now = datetime.datetime.now()
    times = _calendar_times(config)
    if times:
        dur = int(config.get("calendar_duration_minutes", 0) or 0) or 3
        for t in times:
            hm = _parse_hhmm(t)
            start = now.replace(hour=hm[0], minute=hm[1], second=0, microsecond=0)
            if start <= now < start + datetime.timedelta(minutes=dur):
                return True
        return False
    return now.minute in (15, 45) and now.second <= 30


def render_agenda_panel(target, config):
    """Draw the agenda filling `target` (a half-screen surface). Returns True
    if drawn. Used by the split-screen info panel."""
    events = _get_calendar_events(config)
    _render_scrolling_calendar(target, events or [], config, fill=True)
    return True


def show_calendar_if_scheduled(screens, config):
    """Full-screen overlay version (non-split mode): show the agenda at each
    configured time of day as a right-side panel over the photo."""
    if not agenda_in_window(config):
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


def _render_scrolling_calendar(screen, events, config, fill=False):
    """Render a Today / Tomorrow agenda. As a right-side panel by default, or
    filling the surface when fill=True (split-screen info panel)."""
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
        if fill:                       # split-screen: fill the panel half
            panel_w = screen_w - 24
            panel_h = screen_h - 24
            x = 12
            y = 12
        else:                          # overlay: right-side panel
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
