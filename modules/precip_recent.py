"""Measured rain/snow over the last 24 hours.

OpenWeatherMap's free tier only reports precipitation for the last 1-3 hours and
charges for history, so this uses Open-Meteo (free, no API key) which serves past
days. The location is geocoded once from config['location'] (e.g. "Hamilton,CA")
and cached, as is the 24h total (refreshed every 30 min).

Returns amounts in metric: rain/liquid in mm, snowfall in cm.
"""

import os
import json
import time
import datetime

from modules.logger import log_error

CACHE_FILE = "precip_cache.json"
_TTL = 1800                     # refresh the 24h total every 30 min
_GEO_URL = "https://geocoding-api.open-meteo.com/v1/search"
_FORECAST_URL = "https://api.open-meteo.com/v1/forecast"


def _load_cache():
    try:
        with open(CACHE_FILE) as f:
            return json.load(f)
    except Exception:
        return {}


def _save_cache(data):
    try:
        with open(CACHE_FILE, "w") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        log_error(f"Failed to save precip cache: {e}")


def _coords(config, cache):
    """Lat/lon for the configured location, geocoded once and cached."""
    lat, lon = config.get("weather_lat"), config.get("weather_lon")
    if lat not in (None, "") and lon not in (None, ""):
        return float(lat), float(lon)
    if cache.get("lat") is not None and cache.get("lon") is not None:
        return cache["lat"], cache["lon"]

    import requests
    loc = str(config.get("location", "") or "").strip()
    if not loc:
        return None, None
    parts = [p.strip() for p in loc.split(",") if p.strip()]
    params = {"name": parts[0], "count": 1, "language": "en", "format": "json"}
    if len(parts) > 1 and len(parts[-1]) == 2:
        params["country_code"] = parts[-1].upper()
    r = requests.get(_GEO_URL, params=params, timeout=10)
    r.raise_for_status()
    results = (r.json() or {}).get("results") or []
    if not results:
        return None, None
    top = results[0]
    # Remember which place we actually resolved to — a wrong "Hamilton" is the
    # easiest way for these numbers to look wrong (see precip_check.py).
    cache["place"] = ", ".join(str(x) for x in
                               (top.get("name"), top.get("admin1"), top.get("country")) if x)
    return float(top["latitude"]), float(top["longitude"])


def last_24h(config):
    """(rain_mm, snow_cm) measured over the last 24 hours, or None if unavailable."""
    if not config.get("precip_24h_enabled", True):
        return None
    cache = _load_cache()
    now = time.time()
    if cache.get("ts") and (now - cache["ts"]) < _TTL and "rain_mm" in cache:
        return cache.get("rain_mm"), cache.get("snow_cm")

    try:
        import requests
        lat, lon = _coords(config, cache)
        if lat is None:
            return None
        r = requests.get(_FORECAST_URL, params={
            "latitude": lat, "longitude": lon,
            "hourly": "precipitation,snowfall",
            "past_days": 2, "forecast_days": 1, "timezone": "auto",
        }, timeout=10)
        r.raise_for_status()
        hourly = (r.json() or {}).get("hourly") or {}
        times = hourly.get("time") or []
        rain = hourly.get("precipitation") or []
        snow = hourly.get("snowfall") or []

        # Sum the hours falling inside the last 24h (local time, not future).
        now_local = datetime.datetime.now()
        cutoff = now_local - datetime.timedelta(hours=24)
        rain_mm = snow_cm = 0.0
        for i, t in enumerate(times):
            try:
                dt = datetime.datetime.fromisoformat(t)
            except Exception:
                continue
            if not (cutoff <= dt <= now_local):
                continue
            if i < len(rain) and rain[i] is not None:
                rain_mm += float(rain[i])
            if i < len(snow) and snow[i] is not None:
                snow_cm += float(snow[i])

        cache.update({"lat": lat, "lon": lon, "ts": now,
                      "rain_mm": round(rain_mm, 1), "snow_cm": round(snow_cm, 1)})
        _save_cache(cache)
        return cache["rain_mm"], cache["snow_cm"]
    except Exception as e:
        log_error(f"24h precipitation fetch failed: {e}")
        # Fall back to the last known figures rather than showing nothing.
        if "rain_mm" in cache:
            return cache.get("rain_mm"), cache.get("snow_cm")
        return None


def summary_line(config):
    """Short label for the forecast panel, e.g. 'Last 24h: 12 mm rain'."""
    vals = last_24h(config)
    if vals is None:
        return ""
    rain_mm, snow_cm = vals
    snow_cm = snow_cm or 0.0
    rain_mm = rain_mm or 0.0
    if snow_cm >= 0.1:
        # precipitation includes the snow's water equivalent; show the snow depth
        return f"Last 24h: {snow_cm:g} cm snow"
    if rain_mm >= 0.1:
        return f"Last 24h: {rain_mm:g} mm rain"
    return "Last 24h: dry"
