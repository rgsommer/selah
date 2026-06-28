"""Weather display overlay using OpenWeatherMap API."""

import datetime
import json
import time
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

    if time.time() < _show_until:
        screen = screens.get("landscape") or screens.get("portrait")
        if not screen:
            return
        # The scheduled showing is the 5-day forecast; fall back to the current
        # conditions card if the forecast isn't available.
        forecast = _get_forecast(config)
        if forecast:
            _render_forecast(screen, forecast, config)
        else:
            weather = _get_weather(config)
            if weather:
                _render_weather(screen, weather, config)


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
                from modules.new_photo_hint import draw_eyes
                draw_eyes(target, 14 + surf.get_width() + max(10, bar_h // 3),
                          by + bar_h // 2, bar_h)
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
            rec = days.setdefault(key, {"hi": t, "lo": t, "conds": {}, "noon": None})
            rec["hi"] = max(rec["hi"], t)
            rec["lo"] = min(rec["lo"], t)
            rec["conds"][main] = rec["conds"].get(main, 0) + 1
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
            })
        return out
    except Exception as e:
        log_error(f"Forecast fetch failed: {e}")
        return None


def _render_forecast(screen, forecast, config):
    """Render the 5-day forecast as a centered panel."""
    try:
        w, h = screen.get_size()
        n = len(forecast)
        if not n:
            return
        panel_w = min(w - 40, max(480, n * 150))
        panel_h = max(170, h // 4)
        px, py = (w - panel_w) // 2, (h - panel_h) // 2

        bg = pygame.Surface((panel_w, panel_h), pygame.SRCALPHA)
        bg.fill((8, 16, 40, 205))
        screen.blit(bg, (px, py))

        title_font = pygame.font.Font(None, max(28, w // 32))
        day_font = pygame.font.Font(None, max(24, w // 44))
        small = pygame.font.Font(None, max(20, w // 56))
        screen.blit(title_font.render("5-Day Forecast", True, (120, 200, 255)),
                    (px + 16, py + 12))

        col_w = panel_w // n
        top = py + 18 + title_font.get_linesize()
        line = small.get_linesize() + 4
        for i, d in enumerate(forecast):
            cx = px + i * col_w + col_w // 2
            day_s = day_font.render(d["day"], True, (255, 255, 255))
            screen.blit(day_s, day_s.get_rect(center=(cx, top)))
            hilo = small.render(f"{d['hi']}° / {d['lo']}°", True, (225, 225, 225))
            screen.blit(hilo, hilo.get_rect(center=(cx, top + day_font.get_linesize() + 6)))
            cond = small.render(_short(d.get("desc", "")), True, (180, 195, 220))
            screen.blit(cond, cond.get_rect(center=(cx, top + day_font.get_linesize() + 6 + line)))
        try:
            pygame.display.flip()
        except Exception:
            pass
    except Exception as e:
        log_error(f"Forecast render failed: {e}")


def _short(text, n=14):
    text = str(text)
    return text if len(text) <= n else text[:n - 1] + "…"


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


def _cloud(surf, cx, cy, r, color):
    pygame.draw.circle(surf, color, (cx - r // 2, cy), r // 2)
    pygame.draw.circle(surf, color, (cx + r // 2, cy), r // 2)
    pygame.draw.circle(surf, color, (cx, cy - r // 4), int(r * 0.6))
    pygame.draw.rect(surf, color, (cx - r, cy, 2 * r, r // 2 + 1))


def _draw_weather_icon(surf, cx, cy, r, main):
    """Draw a small sun/cloud/rain/snow/storm glyph (default font can't do emoji)."""
    import math
    m = (main or "").lower()
    try:
        if "clear" in m:
            pygame.draw.circle(surf, (255, 210, 80), (cx, cy), r)
            for ang in range(0, 360, 45):
                dx, dy = math.cos(math.radians(ang)), math.sin(math.radians(ang))
                pygame.draw.line(surf, (255, 210, 80),
                                 (cx + dx * (r + 2), cy + dy * (r + 2)),
                                 (cx + dx * (r + r // 2), cy + dy * (r + r // 2)), 2)
        elif "rain" in m or "drizzle" in m:
            _cloud(surf, cx, cy - r // 3, r, (185, 190, 200))
            for i in (-1, 0, 1):
                pygame.draw.line(surf, (90, 150, 230),
                                 (cx + i * r // 2, cy + r // 2), (cx + i * r // 2 - 2, cy + r), 2)
        elif "snow" in m:
            _cloud(surf, cx, cy - r // 3, r, (215, 220, 230))
            for i in (-1, 0, 1):
                pygame.draw.circle(surf, (255, 255, 255), (cx + i * r // 2, cy + r // 2 + 3), 2)
        elif "thunder" in m:
            _cloud(surf, cx, cy - r // 3, r, (160, 160, 175))
            pygame.draw.polygon(surf, (255, 220, 60),
                                [(cx, cy), (cx - r // 3, cy + r // 2), (cx, cy + r // 3), (cx + r // 4, cy + r)])
        elif "cloud" in m:
            _cloud(surf, cx, cy, r, (210, 212, 218))
        else:  # mist / fog / haze
            for i in range(3):
                pygame.draw.line(surf, (200, 200, 205),
                                 (cx - r, cy - r // 2 + i * (r // 2)), (cx + r, cy - r // 2 + i * (r // 2)), 2)
    except Exception:
        pass


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
