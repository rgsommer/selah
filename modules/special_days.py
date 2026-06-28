"""Special-day automation engine for Selah.

Realizes the "built-in automation for special days" part of the vision: a
small, family-maintained list of birthdays, anniversaries, and custom days.
Each morning Selah checks the list and, on a match, automatically:

  * pops a celebratory toast ("Happy Birthday, Mom!"),
  * shows a full-screen celebration splash, and
  * (optionally) biases the slideshow toward that person's photos for the day
    via a filename keyword.

Unlike the email-driven "Happy Birthday Mom May 10" flow, this needs no one to
remember to send anything — the date is enough.

special_days.json format (a list of entries)::

    [
      {"name": "Mom",        "date": "05-10",     "type": "birthday"},
      {"name": "Mom & Dad",  "date": "1985-06-22","type": "anniversary"},
      {"name": "Canada Day", "date": "07-01",     "type": "holiday",
       "message": "Happy Canada Day! \U0001F1E8\U0001F1E6"},
      {"name": "Grandpa",    "date": "03-15",     "type": "birthday",
       "photo_keyword": "grandpa"}
    ]

`date` may be "MM-DD" (recurs yearly) or "YYYY-MM-DD" (recurs yearly on that
month/day; the year lets us compute age / years-married). `message` overrides
the auto-generated text. `photo_keyword` biases today's slideshow.
"""

import datetime
import json
import os
import time

import pygame

from modules.logger import log_error
from modules.toast import queue_toast

_last_celebrated_date = None   # ISO date we've already handled
_last_check_ts = 0             # throttle file scans to once a minute
_active_keywords = []          # photo keywords to prefer for the current day
_active_keywords_date = None


def _load_entries(config):
    path = config.get("special_days_file", "special_days.json")
    try:
        if not os.path.exists(path):
            return []
        with open(path, "r") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception as e:
        log_error(f"Failed to load special days: {e}")
        return []


def get_todays_special_days(config, today=None):
    """Return the list of entries whose date matches today (year-agnostic)."""
    today = today or datetime.date.today()
    mmdd = today.strftime("%m-%d")
    matches = []
    for entry in _load_entries(config):
        raw = str(entry.get("date", "")).strip()
        if not raw:
            continue
        # Match "MM-DD" exactly, or "YYYY-MM-DD" by its month/day suffix.
        if raw == mmdd or raw.endswith("-" + mmdd):
            matches.append(entry)

    # Also celebrate family/friends whose birthday is today (from contacts.json),
    # biasing the slideshow toward their photos via photo_keyword.
    try:
        from modules import contacts as _contacts
        for c in _contacts.todays_birthday_contacts(today):
            email = c.get("email", "")
            matches.append({
                "name": c.get("name") or _contacts.derive_name(email),
                "type": "birthday",
                "date": c.get("birthday"),
                "photo_keyword": c.get("photo_keyword") or _contacts.derive_keyword(email),
            })
    except Exception as e:
        log_error(f"Contact birthday lookup failed: {e}")

    return matches


def _years_since(entry, today):
    """If the entry carries a full YYYY-MM-DD, return whole years elapsed."""
    raw = str(entry.get("date", "")).strip()
    parts = raw.split("-")
    if len(parts) == 3 and len(parts[0]) == 4:
        try:
            start = int(parts[0])
            return today.year - start
        except ValueError:
            return None
    return None


def _default_message(entry, today):
    name = entry.get("name", "").strip()
    etype = (entry.get("type") or "custom").lower()
    yrs = _years_since(entry, today)

    if etype == "birthday":
        base = f"\U0001F389 Happy Birthday, {name}!" if name else "\U0001F389 Happy Birthday!"
        if yrs and yrs > 0:
            base += f"  ({yrs} today)"
        return base
    if etype == "anniversary":
        base = f"\U0001F48D Happy Anniversary, {name}!" if name else "\U0001F48D Happy Anniversary!"
        if yrs and yrs > 0:
            base += f"  ({yrs} years)"
        return base
    if etype == "holiday":
        return f"\U00002728 {name}" if name else "\U00002728 Today is a special day"
    return name or "Today is a special day"


def get_active_photo_keywords():
    """Filenames containing any of these (lowercased) should be favored today.

    image_loader consults this so the birthday person's photos surface on
    their day. Returns [] when nothing special is active.
    """
    if _active_keywords_date == datetime.date.today().isoformat():
        return _active_keywords
    return []


def prioritize_for_today(files, config):
    """Front-load files whose path contains today's active keyword(s).

    Matches the whole path (not just the filename), so a keyword like
    "sarah-lynn" pulls in photos kept in a folder named for that person —
    e.g. media/display/5Sarah-Lynn/anything.jpg. No-op when no special day
    with a photo_keyword is active, so it's safe to call on every refresh.
    """
    keywords = get_active_photo_keywords()
    if not keywords or not files:
        return files
    matched, rest = [], []
    for f in files:
        path = str(f).lower()
        (matched if any(k in path for k in keywords) else rest).append(f)
    return matched + rest if matched else files


def check_special_days(screens, config, state=None):
    """Once per day (after the configured time) celebrate any matching days.

    Cheap to call every loop: it self-throttles to one file scan a minute and
    one celebration a day.
    """
    global _last_celebrated_date, _last_check_ts
    global _active_keywords, _active_keywords_date

    now_ts = time.time()
    if now_ts - _last_check_ts < 60:
        return
    _last_check_ts = now_ts

    now = datetime.datetime.now()
    today = now.date().isoformat()
    if _last_celebrated_date == today:
        return

    # Hold the celebration until the configured morning time so it doesn't fire
    # at midnight to an empty room.
    trigger = config.get("special_days_time", "07:00")
    if now.strftime("%H:%M") < trigger:
        return

    days = get_todays_special_days(config, now.date())
    _last_celebrated_date = today  # mark handled regardless, so we only fire once

    if not days:
        _active_keywords = []
        _active_keywords_date = today
        # No birthday today — stop boosting anyone by face.
        config["priority_person"] = None
        return

    # Arm photo keywords for the day (filename-based biasing).
    keywords = []
    for d in days:
        kw = str(d.get("photo_keyword", "")).strip().lower()
        if kw:
            keywords.append(kw)
    _active_keywords = keywords
    _active_keywords_date = today

    # Face-based biasing: point face recognition at today's birthday person so
    # their photos surface even when filenames don't contain their name. Needs
    # enable_face_recognition + a labeled image at known_faces/<keyword>.jpg.
    person = None
    for d in days:
        if (d.get("type") or "").lower() == "birthday":
            person = (d.get("photo_keyword") or "").strip().lower() or None
            if person:
                break
    config["priority_person"] = person

    for d in days:
        msg = d.get("message") or _default_message(d, now.date())
        queue_toast(msg, config.get("notification_duration", 15))
        print(f"[Selah] Special day: {msg}")

    try:
        _show_celebration(screens, config, days, now.date())
    except Exception as e:
        log_error(f"Celebration splash failed: {e}")


def _show_celebration(screens, config, days, today):
    """Render a full-screen celebration splash briefly on every screen."""
    if not screens:
        return
    duration = config.get("special_days_display_seconds", 8)
    end = time.time() + duration
    clock = pygame.time.Clock()

    lines = [d.get("message") or _default_message(d, today) for d in days]

    while time.time() < end:
        for screen in screens.values():
            _draw_splash(screen, lines)
        try:
            pygame.display.flip()
        except Exception:
            pass
        # Allow ESC / early dismiss without swallowing the app's quit.
        for event in pygame.event.get():
            if event.type == pygame.KEYDOWN and event.key in (pygame.K_ESCAPE, pygame.K_RETURN, pygame.K_SPACE):
                return
            if event.type == pygame.QUIT:
                pygame.event.post(event)
                return
        clock.tick(30)


def _draw_splash(screen, lines):
    try:
        w, h = screen.get_size()
        # Warm festive gradient background.
        screen.fill((20, 10, 35))
        band = pygame.Surface((w, h), pygame.SRCALPHA)
        band.fill((120, 40, 110, 90))
        screen.blit(band, (0, 0))

        title_font = pygame.font.Font(None, max(48, w // 14))
        body_font = pygame.font.Font(None, max(32, w // 26))

        title = title_font.render("✦  Celebrate  ✦", True, (255, 215, 90))
        screen.blit(title, title.get_rect(center=(w // 2, h // 3)))

        y = h // 2
        for line in lines:
            surf = body_font.render(line, True, (255, 255, 255))
            screen.blit(surf, surf.get_rect(center=(w // 2, y)))
            y += body_font.get_linesize() + 10

        pygame.draw.rect(screen, (255, 215, 90), (0, 0, w, h), max(4, w // 240))
    except Exception as e:
        log_error(f"Celebration draw failed: {e}")
