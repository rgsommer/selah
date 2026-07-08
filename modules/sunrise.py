"""Sunrise / sunset photos shown in place of the moon (or split-screen by day).

Drop images into the sunrise/ and sunset/ folders. For a window of +/- a few
minutes around today's sunrise or sunset, Selah shows one at random.
"""

import os
import random
import datetime

from modules.logger import log_error

_EXTS = (".jpg", ".jpeg", ".png")

# kind -> (enabled_key, dir_key, default_dir)
_MAP = {
    "sunrise": ("night_sunrise_enabled", "sunrise_dir", "sunrise"),
    "sunset": ("night_sunset_enabled", "sunset_dir", "sunset"),
}


def _event_dt(kind):
    from modules.moon_times import get_sunrise_dt, get_sunset_dt
    return get_sunrise_dt() if kind == "sunrise" else get_sunset_dt()


def _in_window(config, kind, minutes):
    en_key = _MAP[kind][0]
    if not config.get(en_key, True):
        return False
    try:
        dt = _event_dt(kind)
        if not dt:
            return False
        now = datetime.datetime.now().astimezone()
        return abs((now - dt).total_seconds()) <= minutes * 60
    except Exception:
        return False


_chosen = {}   # (kind, date) -> path: one stable photo per event per day


def _pick(config, kind):
    # Choose ONE photo per sunrise/sunset per day and hold it steady through the
    # window (don't re-randomize every render — that flickers/looks busy).
    key = (kind, datetime.date.today().isoformat())
    prev = _chosen.get(key)
    if prev and os.path.exists(prev):
        return prev
    d = config.get(_MAP[kind][1], _MAP[kind][2])
    try:
        files = [os.path.join(d, f) for f in os.listdir(d) if f.lower().endswith(_EXTS)]
        if files:
            p = random.choice(files)
            _chosen[key] = p
            # keep the map tiny — only today's picks matter
            today = datetime.date.today().isoformat()
            for k in [k for k in _chosen if k[1] != today]:
                _chosen.pop(k, None)
            return p
    except Exception as e:
        log_error(f"{kind} folder read failed: {e}")
    return None


def active_event(config):
    """(path, kind, event_dt) for the active sunrise/sunset window, else
    (None, None, None). kind is 'sunrise' or 'sunset'."""
    minutes = config.get("sunrise_window_minutes", 5)
    for kind in ("sunrise", "sunset"):
        if _in_window(config, kind, minutes):
            p = _pick(config, kind)
            if p:
                return p, kind, _event_dt(kind)
    return None, None, None


def active_image(config):
    """A sunrise/sunset photo path if within either window now, else None."""
    return active_event(config)[0]


# Back-compat single-event helpers (sunrise).
def in_window(config, minutes=5):
    return _in_window(config, "sunrise", minutes)


def pick(config):
    return _pick(config, "sunrise")
