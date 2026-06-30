"""Sunrise photos shown in place of the moon around sunrise.

Drop any number of images into the sunrise folder (default 'sunrise/'). For a
window of +/- a few minutes around today's sunrise, Selah shows one at random
instead of the moon on the night info screen.
"""

import os
import random
import datetime

from modules.logger import log_error

_EXTS = (".jpg", ".jpeg", ".png")


def in_window(config, minutes=5):
    """True if now is within +/-`minutes` of today's sunrise."""
    if not config.get("night_sunrise_enabled", True):
        return False
    try:
        from modules.moon_times import get_sunrise_dt
        sr = get_sunrise_dt()
        if not sr:
            return False
        now = datetime.datetime.now().astimezone()
        return abs((now - sr).total_seconds()) <= minutes * 60
    except Exception:
        return False


def pick(config):
    """A random sunrise image path, or None if the folder is empty/missing."""
    d = config.get("sunrise_dir", "sunrise")
    try:
        files = [os.path.join(d, f) for f in os.listdir(d)
                 if f.lower().endswith(_EXTS)]
        if files:
            return random.choice(files)
    except Exception as e:
        log_error(f"Sunrise folder read failed: {e}")
    return None
