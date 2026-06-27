"""Weather display overlay using OpenWeatherMap API."""

import datetime
import json
import time
import pygame
from modules.logger import log_error

_last_weather_check = None
_cached_weather = None

# Daily-schedule state
_shown_for_date = None   # ISO date string the morning card was last shown for
_show_until = 0          # epoch seconds: keep rendering the card until this time


def show_weather_if_scheduled(screens, config):
    """Show the daily weather card once per day at the configured time.

    The spec calls for a morning weather update (default 08:00). Once the
    clock reaches ``weather_time`` we render the card for
    ``weather_display_seconds`` (default 60s) and then not again until the
    next day. ``weather_time`` accepts "HH:MM"; set it to whatever hour the
    family wants their forecast.
    """
    global _shown_for_date, _show_until

    now = datetime.datetime.now()
    today = now.date().isoformat()
    sched = config.get("weather_time", "08:00")

    # Arm the card the first loop on/after the scheduled time each day.
    if _shown_for_date != today and now.strftime("%H:%M") >= sched:
        weather = _get_weather(config)
        if weather:
            _shown_for_date = today
            _show_until = time.time() + config.get("weather_display_seconds", 60)
        else:
            # No data yet (e.g. no network at boot) — retry next loop, don't
            # mark today as shown so we still catch it once the API responds.
            return

    # While the card is "armed", render it each loop so it stays visible
    # over the rotating slideshow for the configured window.
    if time.time() < _show_until:
        weather = _get_weather(config)
        if weather:
            screen = screens.get("landscape") or screens.get("portrait")
            if screen:
                _render_weather(screen, weather, config)


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
