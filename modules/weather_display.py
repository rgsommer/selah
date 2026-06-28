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


def show_status_line(screens, config):
    """Draw a one-line glance bar: time + current temp + today's forecast.

    e.g.  "3:42 PM    14°C    Today 25°C  Clear Sky"

    Time always shows; temp/forecast appear when weather data is available
    (cached from the same OpenWeatherMap fetch the weather card uses). Position
    is "top" or "bottom" per config.
    """
    now = datetime.datetime.now()
    try:
        time_str = now.strftime("%-I:%M %p")  # 3:42 PM (Linux/macOS)
    except Exception:
        time_str = now.strftime("%H:%M")

    parts = [time_str]
    weather = _get_weather(config)
    if weather:
        parts.append(f"{weather['temp']}°C")
        hi = weather.get("temp_max")
        cond = weather.get("description", "")
        if hi is not None:
            parts.append(f"Today {hi}°C  {cond}".strip())
        elif cond:
            parts.append(cond)

    text = "    ".join(parts)
    position = config.get("status_line_position", "top")
    for screen in screens.values():
        _render_status_line(screen, text, position)


def _render_status_line(screen, text, position):
    """Render the glance bar as a thin translucent strip at top or bottom."""
    try:
        w, h = screen.get_size()
        font_size = max(20, w // 50)
        font = pygame.font.Font(None, font_size)
        surf = font.render(text, True, (255, 255, 255))
        bar_h = surf.get_height() + 12
        by = (h - bar_h) if position == "bottom" else 0

        bg = pygame.Surface((w, bar_h), pygame.SRCALPHA)
        bg.fill((0, 0, 0, 150))
        screen.blit(bg, (0, by))
        screen.blit(surf, (14, by + 6))
        try:
            pygame.display.flip()
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

    location = config.get("location", "Hamilton,ON")

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
                "feels_like": round(data["main"]["feels_like"]),
                "description": data["weather"][0]["description"].title(),
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

    fc = _fetch_forecast(api_key, config.get("location", "Hamilton,ON"))
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
def show_weather_pill(screens, config):
    """A small always-on pill in a corner: current temp + condition."""
    if not config.get("weather_pill_enabled", False):
        return
    weather = _get_weather(config)
    if not weather:
        return
    text = f"{weather['temp']}°C  {weather.get('description', '')}".strip()
    pos = config.get("weather_pill_position", "top-right")
    for screen in screens.values():
        _render_pill(screen, text, pos)


def _render_pill(screen, text, pos):
    try:
        w, h = screen.get_size()
        font = pygame.font.Font(None, max(20, w // 55))
        surf = font.render(text, True, (255, 255, 255))
        pad, margin = 8, 14
        pw, ph = surf.get_width() + pad * 2, surf.get_height() + pad * 2
        if pos == "top-left":
            x, y = margin, margin
        elif pos == "bottom-left":
            x, y = margin, h - ph - margin
        elif pos == "bottom-right":
            x, y = w - pw - margin, h - ph - margin
        else:
            x, y = w - pw - margin, margin
        bg = pygame.Surface((pw, ph), pygame.SRCALPHA)
        bg.fill((0, 0, 0, 165))
        screen.blit(bg, (x, y))
        screen.blit(surf, (x + pad, y + pad))
        try:
            pygame.display.flip()
        except Exception:
            pass
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
