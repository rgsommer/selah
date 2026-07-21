"""Measured rain/snow over the last 24 hours.

Forecast models routinely miss real, localized rainfall — during testing every
model reported ~0 mm for Hamilton while the nearby gauge measured 6.3 mm (and
30 mm one town over). So this prefers ACTUAL station observations from
Environment Canada (api.weather.gc.ca, SWOB real-time gauge data, free/no key),
and falls back to Open-Meteo model data outside Canada or if EC is unavailable.

Amounts are metric: precipitation in mm, snowfall in cm.
"""

import os
import json
import time
import math
import re
import datetime

from modules.logger import log_error

CACHE_FILE = "precip_cache.json"
_TTL = 1800                     # refresh the 24h total every 30 min
_GEO_URL = "https://geocoding-api.open-meteo.com/v1/search"
_FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
_EC_STATIONS = "https://api.weather.gc.ca/collections/swob-stations/items"
_EC_OBS = "https://api.weather.gc.ca/collections/swob-realtime/items"


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


def _km(lat1, lon1, lat2, lon2):
    """Great-circle distance in km."""
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


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
    cache["place"] = ", ".join(str(x) for x in
                               (top.get("name"), top.get("admin1"), top.get("country")) if x)
    return float(top["latitude"]), float(top["longitude"])


def ec_last_24h(lat, lon, radius_deg=0.3):
    """Measured precipitation from the nearest Environment Canada gauge.

    Returns (precip_mm, rain_mm, station_label, distance_km) or None. Stations
    report every minute; the hourly 'past 1 hour' value is taken once per clock
    hour (max seen) and summed, so overlapping samples aren't double-counted.
    """
    import requests
    now = datetime.datetime.now(datetime.timezone.utc)
    start = now - datetime.timedelta(hours=25)
    window = (f"{start.strftime('%Y-%m-%dT%H:%M:%SZ')}/"
              f"{now.strftime('%Y-%m-%dT%H:%M:%SZ')}")
    bbox = f"{lon - radius_deg},{lat - radius_deg},{lon + radius_deg},{lat + radius_deg}"

    per = {}        # station code -> {"coords":(lat,lon), "pcpn":{hour:mm}, "rnfl":{hour:mm}}
    offset = 0
    for _ in range(12):                       # bounded pagination
        r = requests.get(_EC_OBS, params={
            "bbox": bbox, "datetime": window, "limit": 500, "offset": offset,
            "f": "json",
            "properties": "pcpn_amt_pst1hr,rnfl_amt_pst1hr,obs_date_tm",
        }, timeout=30)
        r.raise_for_status()
        data = r.json() or {}
        feats = data.get("features") or []
        if not feats:
            break
        for f in feats:
            p = f.get("properties") or {}
            fid = str(p.get("id") or f.get("id") or "")
            m = re.search(r"\d{4}-\d{2}-\d{2}-\d{4}-([A-Z0-9]+)-", fid)
            code = m.group(1) if m else "?"
            rec = per.setdefault(code, {"coords": None, "pcpn": {}, "rnfl": {}})
            c = (f.get("geometry") or {}).get("coordinates")
            if c and rec["coords"] is None:
                rec["coords"] = (c[1], c[0])
            t = p.get("obs_date_tm") or p.get("date_tm-value")
            if not t:
                continue
            hour = str(t)[:13]
            for key, field in (("pcpn", "pcpn_amt_pst1hr"), ("rnfl", "rnfl_amt_pst1hr")):
                v = p.get(field)
                if v in (None, ""):
                    continue
                try:
                    rec[key][hour] = max(rec[key].get(hour, 0.0), float(v))
                except Exception:
                    pass
        offset += len(feats)
        if offset >= (data.get("numberMatched") or 0):
            break

    # Nearest station that actually reported hourly precipitation.
    best = None
    for code, rec in per.items():
        if not rec["pcpn"] or not rec["coords"]:
            continue
        d = _km(lat, lon, rec["coords"][0], rec["coords"][1])
        if best is None or d < best[0]:
            best = (d, code, rec)
    if not best:
        return None
    dist, code, rec = best
    return (round(sum(rec["pcpn"].values()), 1),
            round(sum(rec["rnfl"].values()), 1), code, round(dist, 1))


def _openmeteo_last_24h(lat, lon):
    """Model fallback: (rain_mm, snow_cm) for the last 24h."""
    import requests
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
    return round(rain_mm, 1), round(snow_cm, 1)


def last_24h(config):
    """Measured/estimated precipitation for the last 24h.

    Returns {"precip_mm", "rain_mm", "snow_cm", "source", "station", "km"} or None.
    """
    if not config.get("precip_24h_enabled", True):
        return None
    cache = _load_cache()
    now = time.time()
    if cache.get("ts") and (now - cache["ts"]) < _TTL and "precip_mm" in cache:
        return cache.get("result") or None

    try:
        lat, lon = _coords(config, cache)
        if lat is None:
            return None

        result = None
        if config.get("precip_use_stations", True):
            try:
                ec = ec_last_24h(lat, lon)
                if ec:
                    precip_mm, rain_mm, code, dist = ec
                    result = {"precip_mm": precip_mm, "rain_mm": rain_mm,
                              "snow_cm": 0.0, "source": "station",
                              "station": code, "km": dist}
            except Exception as e:
                log_error(f"EC station precipitation failed: {e}")

        if result is None:                      # outside Canada, or EC unavailable
            rain_mm, snow_cm = _openmeteo_last_24h(lat, lon)
            result = {"precip_mm": rain_mm, "rain_mm": rain_mm, "snow_cm": snow_cm,
                      "source": "model", "station": "", "km": None}

        cache.update({"lat": lat, "lon": lon, "ts": now,
                      "precip_mm": result["precip_mm"], "result": result})
        _save_cache(cache)
        return result
    except Exception as e:
        log_error(f"24h precipitation fetch failed: {e}")
        return cache.get("result") or None      # last known rather than nothing


def summary_line(config):
    """Short label for the forecast panel, e.g. 'Last 24h: 6.3 mm rain'."""
    r = last_24h(config)
    if not r:
        return ""
    precip = r.get("precip_mm") or 0.0
    rain = r.get("rain_mm") or 0.0
    snow_cm = r.get("snow_cm") or 0.0
    if snow_cm >= 0.1:
        return f"Last 24h: {snow_cm:g} cm snow"
    if precip >= 0.1:
        # If the gauge saw it all as rain, say rain; otherwise stay generic
        # (frozen precipitation is reported as water equivalent).
        label = "rain" if rain >= precip - 0.2 else "precip"
        return f"Last 24h: {precip:g} mm {label}"
    return "Last 24h: no precipitation"
