"""Weather display overlay using OpenWeatherMap API."""

import datetime
import json
import time
import math
import pygame
from modules.logger import log_error

_last_weather_check = None
_cached_weather = None

# Schedule state
_shown_slots = set()     # {(date, "HH:MM")} weather slots already fired today
_show_until = 0          # epoch seconds: keep rendering the card until this time


def _times(config):
    """Scheduled weather times: weather_times list, or [weather_time] fallback."""
    times = config.get("weather_times")
    if not times:
        single = (config.get("weather_time") or "").strip()
        times = [single] if single else []
    elif isinstance(times, str):
        times = [times]
    out = []
    for t in times:
        t = str(t).strip()
        try:
            datetime.datetime.strptime(t, "%H:%M")
            out.append(t)
        except ValueError:
            pass
    return out


def _within(now, hhmm, minutes):
    try:
        h, m = hhmm.split(":")
        start = now.replace(hour=int(h), minute=int(m), second=0, microsecond=0)
        return start <= now < start + datetime.timedelta(minutes=minutes)
    except Exception:
        return False


def show_weather_if_scheduled(screens, config):
    """Show the weather card at each configured time of day.

    Set weather_times = ["08:00", "21:30"] for multiple showings (or
    weather_time for a single one). Each crossing renders the card for
    weather_display_seconds. Times missed because the app started later are
    skipped, not replayed.
    """
    if tick_forecast(config):
        screen = screens.get("landscape") or screens.get("portrait")
        if screen:
            render_forecast_panel(screen, config)


def tick_forecast(config):
    """Arm the scheduled forecast at each configured time, and report whether
    it should be on screen right now. Call once per loop."""
    global _show_until, _shown_slots

    now = datetime.datetime.now()
    today = now.date().isoformat()
    cur = now.strftime("%H:%M")
    _shown_slots = {s for s in _shown_slots if s[0] == today}  # drop old days

    for t in _times(config):
        slot = (today, t)
        if slot in _shown_slots or cur < t:
            continue
        if _within(now, t, 2):           # just crossed this time -> arm the card
            if _get_weather(config):
                _show_until = time.time() + config.get("weather_display_seconds", 60)
                _shown_slots.add(slot)
            # else: no data yet (e.g. no network) — retry next loop
        else:
            _shown_slots.add(slot)        # missed the window (late start) — skip

    return time.time() < _show_until


def render_forecast_panel(target, config):
    """Draw the 5-day forecast (or the current-conditions card if no forecast)
    filling `target`. Returns True if drawn."""
    forecast = _get_forecast(config)
    if forecast:
        _render_forecast(target, forecast, config)
        return True
    weather = _get_weather(config)
    if weather:
        _render_weather(target, weather, config)
        return True
    return False


def _status_text(config):
    """Build the glance-bar string: time, optionally temp + today's forecast."""
    now = datetime.datetime.now()
    try:
        time_str = now.strftime("%-I:%M %p")  # 3:42 PM (Linux/macOS)
    except Exception:
        time_str = now.strftime("%H:%M")

    parts = [time_str]
    # The corner weather pill owns the weather glance, so the status line is
    # time-only by default. Opt back in with status_line_weather: true.
    if config.get("status_line_weather", False):
        weather = _get_weather(config)
        if weather:
            parts.append(f"{weather['temp']}°C")
            hi = weather.get("temp_max")
            cond = weather.get("description", "")
            if hi is not None:
                parts.append(f"Today {hi}°C  {cond}".strip())
            elif cond:
                parts.append(cond)
    return "    ".join(parts)


def _eyes_active(config):
    """Whether the subtle 'new photo' eyes hint should show beside the time."""
    try:
        from modules.new_photo_hint import is_active
        return is_active(config)
    except Exception:
        return False


def show_status_line(screens, config):
    """Draw the one-line glance bar straight to the screen(s) and flip."""
    text = _status_text(config)
    position = config.get("status_line_position", "top")
    eyes = _eyes_active(config)
    for screen in screens.values():
        _render_status_line(screen, text, position, eyes)
    try:
        pygame.display.flip()
    except Exception:
        pass


def draw_status_line(screen, config, target):
    """Render the glance bar onto `target` (e.g. a fade layer); no flip.

    Returns True if anything was drawn. `screen` is used only for sizing.
    """
    _render_status_line(target, _status_text(config),
                        config.get("status_line_position", "top"),
                        _eyes_active(config))
    return True


def _render_status_line(target, text, position, show_eyes=False):
    """Render the glance bar as a thin translucent strip at top or bottom."""
    try:
        w, h = target.get_size()
        font_size = max(20, w // 50)
        font = pygame.font.Font(None, font_size)
        surf = font.render(text, True, (255, 255, 255))
        bar_h = surf.get_height() + 12
        by = (h - bar_h) if position == "bottom" else 0

        bg = pygame.Surface((w, bar_h), pygame.SRCALPHA)
        bg.fill((0, 0, 0, 150))
        target.blit(bg, (0, by))
        target.blit(surf, (14, by + 6))
        if show_eyes:
            try:
                from modules.new_photo_hint import draw_glyph, current_kind
                draw_glyph(target, 14 + surf.get_width() + max(10, bar_h // 3),
                           by + bar_h // 2, bar_h, current_kind())
            except Exception:
                pass
    except Exception as e:
        log_error(f"Status line render failed: {e}")


def _get_weather(config):
    """Fetch weather data from OpenWeatherMap or local cache."""
    global _last_weather_check, _cached_weather

    if not config.get("weather_enabled", False):
        return None

    api_key = config.get("weather_api_key", "")
    if not api_key or api_key == "your_openweathermap_api_key":
        return _cached_weather

    location = config.get("location", "Hamilton,CA")

    now = datetime.datetime.now()
    if _last_weather_check and (now - _last_weather_check).seconds < 1800:
        return _cached_weather

    weather = _fetch_openweathermap(api_key, location)
    if weather:
        _cached_weather = weather
        _last_weather_check = now
        try:
            with open("weather_cache.json", "w") as f:
                json.dump(weather, f)
        except Exception:
            pass
    elif not _cached_weather:
        try:
            with open("weather_cache.json", "r") as f:
                _cached_weather = json.load(f)
        except Exception:
            pass

    return _cached_weather


def _fetch_openweathermap(api_key, location):
    """Fetch current weather from OpenWeatherMap API."""
    try:
        import requests
        url = "https://api.openweathermap.org/data/2.5/weather"
        params = {"q": location, "appid": api_key, "units": "metric"}
        response = requests.get(url, params=params, timeout=10)
        if response.status_code == 200:
            data = response.json()
            return {
                "temp": round(data["main"]["temp"]),
                "temp_max": round(data["main"].get("temp_max", data["main"]["temp"])),
                "temp_min": round(data["main"].get("temp_min", data["main"]["temp"])),
                "feels_like": round(data["main"]["feels_like"]),
                "description": data["weather"][0]["description"].title(),
                "main": data["weather"][0]["main"],
                "humidity": data["main"]["humidity"],
                "wind_speed": round(data["wind"]["speed"] * 3.6, 1),
                "city": data.get("name", location),
                "fetched_at": datetime.datetime.now().isoformat(),
            }
        else:
            log_error(f"Weather API returned {response.status_code}")
    except Exception as e:
        log_error(f"Weather fetch failed: {e}")
    return None


# --- 5-day forecast --------------------------------------------------------
_cached_forecast = None
_last_forecast_check = None

# --- optional second location (compact strip on the 5-day panel) -----------
_second_cache = None
_second_check = None


def _get_second_summary(config):
    """Compact current-conditions summary for an optional second location:
    {place, temp, main, hi, lo, boat}. Cached 1h. None when not configured."""
    global _second_cache, _second_check
    if not config.get("weather_enabled", False):
        return None
    loc = (config.get("forecast_second_location") or "").strip()
    if not loc:
        return None
    api_key = config.get("weather_api_key", "")
    if not api_key or api_key == "your_openweathermap_api_key":
        return _second_cache if (_second_cache and _second_cache.get("loc") == loc) else None
    now = datetime.datetime.now()
    if (_second_cache and _second_check and _second_cache.get("loc") == loc
            and (now - _second_check).seconds < 3600):
        return _second_cache
    cur = _fetch_openweathermap(api_key, loc)
    fc = _fetch_forecast(api_key, loc)
    if not cur and not fc:
        return _second_cache if (_second_cache and _second_cache.get("loc") == loc) else None
    today = (fc[0] if fc else {})
    temp = cur.get("temp") if cur else today.get("hi")
    main = (cur.get("main") if cur else today.get("main")) or ""
    place = (cur.get("city") if cur else "") or loc.split(",")[0].strip()
    _second_cache = {
        "loc": loc, "place": place,
        "temp": (round(temp) if temp is not None else None), "main": main,
        "hi": today.get("hi"), "lo": today.get("lo"),
        "boat": (_boating_level(today, config) if today else 0),
    }
    _second_check = now
    return _second_cache


def _get_forecast(config):
    """Daily 5-day forecast (list of {day, hi, lo, desc, main}); cached 1h."""
    global _cached_forecast, _last_forecast_check
    if not config.get("weather_enabled", False):
        return None
    api_key = config.get("weather_api_key", "")
    if not api_key or api_key == "your_openweathermap_api_key":
        return _cached_forecast
    now = datetime.datetime.now()
    if _last_forecast_check and (now - _last_forecast_check).seconds < 3600:
        return _cached_forecast

    fc = _fetch_forecast(api_key, config.get("location", "Hamilton,CA"))
    if fc:
        _cached_forecast = fc
        _last_forecast_check = now
        try:
            with open("forecast_cache.json", "w") as f:
                json.dump(fc, f)
        except Exception:
            pass
    elif not _cached_forecast:
        try:
            with open("forecast_cache.json") as f:
                _cached_forecast = json.load(f)
        except Exception:
            pass
    return _cached_forecast


def _fetch_forecast(api_key, location):
    """OpenWeather 5-day/3-hour forecast aggregated to daily hi/lo/condition."""
    try:
        import requests
        url = "https://api.openweathermap.org/data/2.5/forecast"
        params = {"q": location, "appid": api_key, "units": "metric"}
        r = requests.get(url, params=params, timeout=10)
        if r.status_code != 200:
            log_error(f"Forecast API returned {r.status_code}")
            return None
        days = {}
        for entry in r.json().get("list", []):
            dt = datetime.datetime.fromtimestamp(entry["dt"])
            key = dt.date().isoformat()
            t = entry["main"]["temp"]
            main = entry["weather"][0]["main"]
            desc = entry["weather"][0]["description"].title()
            wnd = entry.get("wind") or {}
            pop = float(entry.get("pop", 0) or 0)      # 0..1 chance of precipitation
            wind = float(wnd.get("speed", 0) or 0)     # m/s
            deg = wnd.get("deg")                       # direction wind blows FROM
            rec = days.setdefault(key, {"hi": t, "lo": t, "conds": {}, "noon": None,
                                        "pop": 0.0, "wind": None, "wind_deg": None})
            rec["hi"] = max(rec["hi"], t)
            rec["lo"] = min(rec["lo"], t)
            rec["conds"][main] = rec["conds"].get(main, 0) + 1
            if 6 <= dt.hour <= 21:                     # daytime max = the useful "chance of rain" / gustiness
                rec["pop"] = max(rec["pop"], pop)
                if rec["wind"] is None or wind > rec["wind"]:
                    rec["wind"] = wind                 # keep the direction of the strongest wind
                    rec["wind_deg"] = deg
            if 11 <= dt.hour <= 15:
                rec["noon"] = desc
        out = []
        for key in sorted(days)[:5]:
            rec = days[key]
            main = max(rec["conds"], key=rec["conds"].get) if rec["conds"] else ""
            out.append({
                "day": datetime.date.fromisoformat(key).strftime("%a"),
                "hi": round(rec["hi"]), "lo": round(rec["lo"]),
                "desc": rec["noon"] or main, "main": main,
                "pop": round(rec["pop"] * 100),
                "wind": (round(rec["wind"], 1) if rec["wind"] is not None else None),
                "wind_deg": rec.get("wind_deg"),
            })
        return out
    except Exception as e:
        log_error(f"Forecast fetch failed: {e}")
        return None


def _wrap(text, font, max_w):
    """Word-wrap `text` to fit `max_w` px; returns a list of lines."""
    words = str(text or "").split()
    lines, cur = [], ""
    for wd in words:
        t = (cur + " " + wd).strip()
        if not cur or font.size(t)[0] <= max_w:
            cur = t
        else:
            lines.append(cur)
            cur = wd
    if cur:
        lines.append(cur)
    return lines


def _draw_weather_icon(s, cx, cy, r, main):
    """Draw a small flat weather glyph centred at (cx, cy) sized by radius r."""
    try:
        m = (main or "").lower()
        SUN = (250, 200, 70)
        CLOUD = (228, 233, 240)
        CLOUD_DK = (150, 160, 176)
        DROP = (95, 155, 240)
        BOLT = (255, 214, 70)

        def sun(ox=0, oy=0, rr=None):
            rr = rr or int(r * 0.55)
            for a in range(0, 360, 45):
                ax, ay = math.cos(math.radians(a)), math.sin(math.radians(a))
                pygame.draw.line(s, SUN,
                                 (cx + ox + ax * rr * 1.25, cy + oy + ay * rr * 1.25),
                                 (cx + ox + ax * rr * 1.7, cy + oy + ay * rr * 1.7),
                                 max(2, r // 12))
            pygame.draw.circle(s, SUN, (cx + ox, cy + oy), rr)

        def cloud(ox=0, oy=0, col=CLOUD, sc=1.0):
            rr = int(r * 0.42 * sc)
            by = cy + oy + int(r * 0.18)
            pygame.draw.circle(s, col, (cx + ox - rr, by), int(rr * 0.85))
            pygame.draw.circle(s, col, (cx + ox + int(rr * 0.2), by - int(rr * 0.6)), rr)
            pygame.draw.circle(s, col, (cx + ox + rr, by), int(rr * 0.8))
            pygame.draw.rect(s, col, (cx + ox - int(rr * 1.7), by, int(rr * 3.2),
                             int(rr * 0.95)), border_radius=int(rr * 0.5))

        def drops(col=DROP, n=3):
            by = cy + int(r * 0.7)
            for k in range(n):
                dx = cx + int((k - (n - 1) / 2) * r * 0.45)
                pygame.draw.line(s, col, (dx, by), (dx - int(r * 0.12), by + int(r * 0.35)),
                                 max(2, r // 10))

        if "clear" in m:
            sun()
        elif "thunder" in m:
            cloud(oy=-int(r * 0.1), col=CLOUD_DK)
            pts = [(cx - r * 0.1, cy + r * 0.35), (cx + r * 0.15, cy + r * 0.35),
                   (cx - r * 0.02, cy + r * 0.7), (cx + r * 0.28, cy + r * 0.3),
                   (cx + r * 0.05, cy + r * 0.3), (cx + r * 0.2, cy + r * 0.05)]
            pygame.draw.polygon(s, BOLT, pts)
        elif "rain" in m or "drizzle" in m:
            cloud(oy=-int(r * 0.12))
            drops()
        elif "snow" in m:
            cloud(oy=-int(r * 0.12))
            for k in range(3):
                dx = cx + int((k - 1) * r * 0.45)
                pygame.draw.circle(s, (235, 240, 250), (dx, cy + int(r * 0.75)), max(2, r // 9))
        elif any(x in m for x in ("mist", "fog", "haze", "smoke")):
            for k in range(3):
                yy = cy - int(r * 0.3) + k * int(r * 0.35)
                pygame.draw.line(s, CLOUD_DK, (cx - r, yy), (cx + r, yy), max(2, r // 9))
        else:  # clouds / default — a little sun peeking behind
            sun(ox=int(r * 0.35), oy=-int(r * 0.35), rr=int(r * 0.4))
            cloud()
    except Exception:
        pass


def _is_nice_day(d, config):
    """True when a day looks pleasant to be outside: comfortable high, low chance
    of rain, and not stormy/snowy. Thresholds are tunable."""
    if not config.get("nice_day_hue", True):
        return False
    hi = d.get("hi")
    if hi is None:
        return False
    main = (d.get("main") or "").lower()
    if any(b in main for b in ("rain", "snow", "thunder", "drizzle", "sleet", "storm")):
        return False
    if (d.get("pop") or 0) > config.get("nice_day_max_pop", 35):
        return False
    return config.get("nice_day_min_c", 16) <= hi <= config.get("nice_day_max_c", 28)


def _boating_level(d, config):
    """0 = not boating weather, 1 = good (🚤), 2 = really good (🛳️). Driven mainly
    by daytime wind, plus warmth, low rain, and no storms. Needs wind data."""
    if not config.get("boating_hint", True):
        return 0
    hi = d.get("hi")
    wind = d.get("wind")
    if hi is None or wind is None:
        return 0
    main = (d.get("main") or "").lower()
    if any(b in main for b in ("rain", "snow", "thunder", "drizzle", "sleet", "storm")):
        return 0
    pop = d.get("pop") or 0
    if (hi >= config.get("boat_great_min_c", 22)
            and pop <= config.get("boat_great_max_pop", 15)
            and wind <= config.get("boat_great_max_wind_ms", 5)):
        return 2
    if (hi >= config.get("boat_good_min_c", 18)
            and pop <= config.get("boat_good_max_pop", 30)
            and wind <= config.get("boat_good_max_wind_ms", 8)):
        return 1
    return 0


def _draw_boat(s, cx, cy, r, great=False):
    """Draw a small speedboat (great=False) or passenger ship (great=True)."""
    try:
        water = (120, 180, 235)
        white = (242, 244, 248)
        if great:
            hull = (58, 68, 88)
            pygame.draw.polygon(s, hull, [(cx - r, cy), (cx + r, cy),
                                          (cx + r * 0.7, cy + r * 0.55),
                                          (cx - r * 0.7, cy + r * 0.55)])
            pygame.draw.rect(s, white, (cx - r * 0.7, cy - r * 0.55, r * 1.4, r * 0.55),
                             border_radius=2)
            pygame.draw.rect(s, white, (cx - r * 0.42, cy - r * 0.95, r * 0.84, r * 0.42),
                             border_radius=2)
            for k in range(4):
                pygame.draw.circle(s, (120, 170, 220),
                                   (int(cx - r * 0.5 + k * r * 0.33), int(cy - r * 0.28)),
                                   max(1, int(r * 0.07)))
            pygame.draw.rect(s, (70, 80, 95), (cx + r * 0.02, cy - r * 1.25, r * 0.26, r * 0.4))
            pygame.draw.rect(s, (205, 90, 70), (cx + r * 0.02, cy - r * 1.25, r * 0.26, r * 0.13))
        else:
            hull = (208, 62, 55)
            pygame.draw.polygon(s, hull, [(cx - r, cy), (cx + r * 0.95, cy),
                                          (cx + r * 0.55, cy + r * 0.5),
                                          (cx - r * 0.6, cy + r * 0.5)])
            pygame.draw.line(s, white, (cx - r * 0.9, cy), (cx + r * 0.85, cy),
                             max(1, int(r * 0.16)))
            pygame.draw.polygon(s, (150, 195, 235),
                                [(cx - r * 0.1, cy), (cx + r * 0.35, cy), (cx + r * 0.15, cy - r * 0.42)])
        pygame.draw.line(s, water, (cx - r, cy + r * 0.62), (cx + r, cy + r * 0.62),
                         max(2, int(r * 0.16)))
    except Exception:
        pass


_COMPASS = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
            "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]


def _compass(deg):
    """16-point compass label for a bearing (direction wind blows FROM)."""
    if deg is None:
        return ""
    try:
        return _COMPASS[int((float(deg) % 360) / 22.5 + 0.5) % 16]
    except Exception:
        return ""


def _draw_wind_arrow(s, cx, cy, size, from_deg):
    """Small arrow showing where the wind is blowing TO (from_deg is the FROM
    bearing; N=up, E=right on screen)."""
    if from_deg is None:
        return
    try:
        to = math.radians((float(from_deg) + 180) % 360)
        dx, dy = math.sin(to), -math.cos(to)
        tip = (cx + dx * size, cy + dy * size)
        tail = (cx - dx * size, cy - dy * size)
        col = (200, 215, 235)
        pygame.draw.line(s, col, tail, tip, max(2, size // 4))
        # arrowhead
        left = math.radians((float(from_deg) + 180 + 140) % 360)
        right = math.radians((float(from_deg) + 180 - 140) % 360)
        for ang in (left, right):
            hx, hy = math.sin(ang), -math.cos(ang)
            pygame.draw.line(s, col, tip, (tip[0] + hx * size * 0.7, tip[1] + hy * size * 0.7),
                             max(2, size // 4))
    except Exception:
        pass


def _render_forecast(screen, forecast, config):
    """Render the 5-day forecast as a centred panel with an icon, hi/lo, chance of
    rain, wind (km/h), and a wrapped condition per day. Pleasant outdoor days get
    a green tint; good boating days get a boat badge."""
    try:
        w, h = screen.get_size()
        n = len(forecast)
        if not n:
            return
        title_font = pygame.font.Font(None, max(30, w // 30))
        day_font = pygame.font.Font(None, max(26, w // 40))
        temp_font = pygame.font.Font(None, max(24, w // 46))
        small = pygame.font.Font(None, max(20, w // 54))

        second = _get_second_summary(config)                 # optional footer strip
        foot_h = (day_font.get_linesize() + 22) if second else 0

        col_w = max(150, min(210, (w - 60) // n))
        panel_w = min(w - 30, n * col_w)
        panel_h = min(h - 20, max(360, h // 3) + foot_h)
        px, py = (w - panel_w) // 2, (h - panel_h) // 2
        col_w = panel_w // n
        content_bottom = py + panel_h - foot_h               # columns stop above the footer

        bg = pygame.Surface((panel_w, panel_h), pygame.SRCALPHA)
        pygame.draw.rect(bg, (10, 18, 42, 214), bg.get_rect(), border_radius=16)
        pygame.draw.rect(bg, (60, 110, 180, 230), bg.get_rect(), width=2, border_radius=16)
        screen.blit(bg, (px, py))

        t_s = title_font.render("5-Day Forecast", True, (130, 205, 255))
        screen.blit(t_s, (px + 18, py + 14))

        today = datetime.datetime.now().strftime("%a")
        top = py + 20 + title_font.get_linesize()
        icon_r = max(16, col_w // 6)

        for i, d in enumerate(forecast):
            cx = px + i * col_w + col_w // 2
            col_left = px + i * col_w
            is_today = d.get("day") == today
            nice = _is_nice_day(d, config)
            # Column tint: green for a pleasant-outdoors day, blue for today.
            if nice or is_today:
                hl_h = content_bottom - (top - 6) - 4
                hl = pygame.Surface((col_w - 6, hl_h), pygame.SRCALPHA)
                hl.fill((70, 180, 95, 70) if nice else (90, 150, 220, 45))
                screen.blit(hl, (col_left + 3, top - 6))
                if is_today and nice:   # both — mark today with a thin border too
                    pygame.draw.rect(screen, (150, 200, 255, 220),
                                     (col_left + 3, top - 6, col_w - 6, hl_h),
                                     width=2, border_radius=8)

            # boating badge in the column's top-right corner
            lvl = _boating_level(d, config)
            if lvl:
                br = max(11, col_w // 11)
                _draw_boat(screen, col_left + col_w - br - 8, top + br + 2, br, great=(lvl == 2))

            y = top
            day_s = day_font.render(d["day"], True, (255, 255, 255))
            screen.blit(day_s, day_s.get_rect(center=(cx, y)))
            y += day_font.get_linesize() // 2 + icon_r + 8

            _draw_weather_icon(screen, cx, y, icon_r, d.get("main"))
            y += icon_r + temp_font.get_linesize() // 2 + 6

            hilo = temp_font.render(f"{d['hi']}° / {d['lo']}°", True, (235, 235, 235))
            screen.blit(hilo, hilo.get_rect(center=(cx, y)))
            y += temp_font.get_linesize() + 2

            pop = d.get("pop")
            if pop:
                # a tiny drop + percentage
                dtxt = small.render(f"{pop}%", True, (150, 195, 245))
                dw = dtxt.get_width()
                drop_x = cx - dw // 2 - 8
                pygame.draw.circle(screen, (95, 155, 240), (drop_x, y), max(3, small.get_height() // 4))
                screen.blit(dtxt, dtxt.get_rect(midleft=(cx - dw // 2 + 2, y)))
                y += small.get_linesize() + 2

            wind = d.get("wind")
            if wind is not None:
                deg = d.get("wind_deg")
                label = f"{round(wind * 3.6)} km/h"
                comp = _compass(deg)
                if comp:
                    label += f" {comp}"
                wtxt = small.render(label, True, (175, 200, 220))
                ww = wtxt.get_width()
                ar = small.get_height() // 2
                # a small direction arrow to the left, then the text
                _draw_wind_arrow(screen, cx - ww // 2 - 14, y, ar, deg)
                screen.blit(wtxt, wtxt.get_rect(midleft=(cx - ww // 2, y)))
                y += small.get_linesize() + 2

            for ln in _wrap(d.get("desc", ""), small, col_w - 14)[:2]:
                ls = small.render(ln, True, (185, 200, 225))
                screen.blit(ls, ls.get_rect(center=(cx, y)))
                y += small.get_linesize()

        # --- optional second-location strip along the bottom ---
        if second and foot_h:
            fy0 = py + panel_h - foot_h
            pygame.draw.line(screen, (60, 95, 150), (px + 18, fy0 + 3),
                             (px + panel_w - 18, fy0 + 3), 1)
            fy = fy0 + foot_h // 2 + 3
            x = px + 22
            place_s = day_font.render(second.get("place", ""), True, (255, 255, 255))
            screen.blit(place_s, place_s.get_rect(midleft=(x, fy)))
            x += place_s.get_width() + 22
            ir = max(12, small.get_height() // 2 + 5)
            _draw_weather_icon(screen, x + ir, fy, ir, second.get("main"))
            x += ir * 2 + 16
            if second.get("temp") is not None:
                ct = temp_font.render(f"{second['temp']}°", True, (240, 240, 240))
                screen.blit(ct, ct.get_rect(midleft=(x, fy)))
                x += ct.get_width() + 20
            if second.get("hi") is not None:
                hlt = small.render(f"H {second['hi']}°   L {second['lo']}°", True, (200, 215, 235))
                screen.blit(hlt, hlt.get_rect(midleft=(x, fy)))
                x += hlt.get_width() + 20
            if second.get("boat"):
                br = max(11, foot_h // 3)
                _draw_boat(screen, x + br, fy, br, great=(second["boat"] == 2))

        try:
            pygame.display.flip()
        except Exception:
            pass
    except Exception as e:
        log_error(f"Forecast render failed: {e}")


# --- Persistent corner pill (current conditions) ---------------------------
def _pill_data(config):
    """Return (weather, hi, lo, pos) for the corner pill, or None if no data."""
    if not config.get("weather_pill_enabled", False):
        return None
    weather = _get_weather(config)
    if not weather:
        return None
    # Prefer today's High/Low from the 5-day forecast (the current-conditions
    # endpoint reports min≈max≈now, so it can't give a real daily range).
    hi = weather.get("temp_max", weather["temp"])
    lo = weather.get("temp_min", weather["temp"])
    forecast = _get_forecast(config)
    if forecast:
        today = datetime.datetime.now().strftime("%a")
        td = next((d for d in forecast if d.get("day") == today), forecast[0])
        hi, lo = td.get("hi", hi), td.get("lo", lo)
    return weather, hi, lo, config.get("weather_pill_position", "top-right")


def show_weather_pill(screens, config):
    """A small always-on pill in a corner: current temp + icon + today's High/Low."""
    data = _pill_data(config)
    if not data:
        return
    weather, hi, lo, pos = data
    for screen in screens.values():
        _render_pill(screen, weather, pos, hi, lo)
    try:
        pygame.display.flip()
    except Exception:
        pass


def draw_weather_pill(screen, config, target):
    """Render the pill onto `target` (e.g. a fade layer); no flip.

    Returns True if drawn. `screen` is used only for sizing.
    """
    data = _pill_data(config)
    if not data:
        return False
    weather, hi, lo, pos = data
    _render_pill(target, weather, pos, hi, lo)
    return True


def _render_pill(target, weather, pos, hi=None, lo=None):
    try:
        if hi is None:
            hi = weather.get("temp_max", weather["temp"])
        if lo is None:
            lo = weather.get("temp_min", weather["temp"])
        w, h = target.get_size()
        font = pygame.font.Font(None, max(22, w // 50))
        temp_s = font.render(f"{weather['temp']}°", True, (255, 255, 255))
        high_s = font.render(f"H{hi}°  L{lo}°", True, (210, 220, 235))

        pad, gap = 9, 9
        icon_r = max(7, font.get_height() // 3)
        icon_w = icon_r * 3
        pw = pad * 2 + temp_s.get_width() + gap + icon_w + gap + high_s.get_width()
        ph = pad * 2 + max(temp_s.get_height(), icon_r * 2 + 4)

        margin = 14
        if pos == "top-left":
            x, y = margin, margin
        elif pos == "bottom-left":
            x, y = margin, h - ph - margin
        elif pos == "bottom-right":
            x, y = w - pw - margin, h - ph - margin
        else:
            x, y = w - pw - margin, margin

        bg = pygame.Surface((pw, ph), pygame.SRCALPHA)
        bg.fill((0, 0, 0, 170))
        target.blit(bg, (x, y))

        cy = y + ph // 2
        cx = x + pad
        target.blit(temp_s, (cx, cy - temp_s.get_height() // 2))
        cx += temp_s.get_width() + gap + icon_w // 2
        _draw_weather_icon(target, cx, cy, icon_r, weather.get("main", ""))
        cx += icon_w // 2 + gap
        target.blit(high_s, (cx, cy - high_s.get_height() // 2))
    except Exception as e:
        log_error(f"Weather pill render failed: {e}")


def _render_weather(screen, weather, config):
    """Render weather info as a small overlay in the top-right corner."""
    try:
        screen_w, screen_h = screen.get_size()
        font_size = max(28, screen_w // 30)
        small_size = max(22, screen_w // 40)

        font = pygame.font.Font(None, font_size)
        small_font = pygame.font.Font(None, small_size)
        big_font = pygame.font.Font(None, int(font_size * 1.8))

        temp_str = f"{weather['temp']}\u00b0C"
        desc_str = weather.get("description", "")
        feels_str = f"Feels like {weather.get('feels_like', weather['temp'])}\u00b0C"
        city_str = weather.get("city", "")

        lines = [
            (big_font, temp_str),
            (font, desc_str),
            (small_font, feels_str),
            (small_font, city_str),
        ]
        max_text_w = max(f.size(t)[0] for f, t in lines)
        box_w = max_text_w + 40
        total_h = sum(f.get_linesize() for f, _ in lines) + 40

        box_x = screen_w - box_w - 20
        box_y = 20

        bg = pygame.Surface((box_w, total_h), pygame.SRCALPHA)
        bg.fill((0, 0, 0, 160))
        screen.blit(bg, (box_x, box_y))

        y = box_y + 10
        for f, text in lines:
            surf = f.render(text, True, (255, 255, 255))
            screen.blit(surf, (box_x + 15, y))
            y += f.get_linesize() + 2

        try:
            pygame.display.flip()
        except Exception:
            pass
    except Exception as e:
        log_error(f"Weather render failed: {e}")
