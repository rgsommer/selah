"""Moonrise / moonset times.

Fetched once a day in the background from met.no's free Sunrise API (no key,
just a descriptive User-Agent). The location's lat/lon comes from OpenWeather's
geocoder using the weather_api_key you already have. Cached for the day and
displayed under the moon at night.
"""

import datetime
import threading

from modules.logger import log_error

_state = {"date": None, "rise": None, "set": None,
          "sunrise": None, "sunset": None, "latlon": None}
_lock = threading.Lock()
_thread = None

_UA = "SelahPhotoFrame/1.0 (github.com/rgsommer/selah)"


def _geocode(config):
    if _state["latlon"]:
        return _state["latlon"]
    try:
        import requests
        key = config.get("weather_api_key", "")
        loc = config.get("location", "")
        if not key or not loc:
            return None
        r = requests.get("http://api.openweathermap.org/geo/1.0/direct",
                         params={"q": loc, "limit": 1, "appid": key}, timeout=10)
        d = r.json()
        if d:
            _state["latlon"] = (d[0]["lat"], d[0]["lon"])
            return _state["latlon"]
    except Exception as e:
        log_error(f"Geocode failed: {e}")
    return None


def _fmt(iso):
    try:
        return datetime.datetime.fromisoformat(iso).astimezone().strftime("%-I:%M %p")
    except Exception:
        return None


def _endpoint(kind, lat, lon, today):
    import requests
    r = requests.get(f"https://api.met.no/weatherapi/sunrise/3.0/{kind}",
                     params={"lat": round(lat, 4), "lon": round(lon, 4), "date": today},
                     headers={"User-Agent": _UA}, timeout=12)
    return r.json().get("properties", {})


def _fetch(config, today):
    ll = _geocode(config)
    if not ll:
        return
    lat, lon = ll
    upd = {"date": today}
    try:
        m = _endpoint("moon", lat, lon, today)
        upd["rise"] = _fmt(m.get("moonrise", {}).get("time"))
        upd["set"] = _fmt(m.get("moonset", {}).get("time"))
    except Exception as e:
        log_error(f"Moon times fetch failed: {e}")
    try:
        s = _endpoint("sun", lat, lon, today)
        upd["sunrise"] = _fmt(s.get("sunrise", {}).get("time"))
        upd["sunset"] = _fmt(s.get("sunset", {}).get("time"))
    except Exception as e:
        log_error(f"Sun times fetch failed: {e}")
    with _lock:
        _state.update(upd)


def refresh_moon_times(config):
    """Kick off a daily background fetch (self-throttling; safe to call often)."""
    global _thread
    if not config.get("moon_times_enabled", True) or not config.get("weather_api_key"):
        return
    today = datetime.date.today().isoformat()
    with _lock:
        if _state["date"] == today:
            return
        if _thread is not None and _thread.is_alive():
            return
    _thread = threading.Thread(target=_fetch, args=(config, today), daemon=True)
    _thread.start()


def get_cached():
    """Return (moonrise, moonset) display strings, or None if not fetched yet."""
    with _lock:
        if _state["rise"] or _state["set"]:
            return _state["rise"] or "—", _state["set"] or "—"
    return None


def get_sun():
    """Return (sunrise, sunset) display strings, or None if not fetched yet."""
    with _lock:
        if _state["sunrise"] or _state["sunset"]:
            return _state["sunrise"] or "—", _state["sunset"] or "—"
    return None
