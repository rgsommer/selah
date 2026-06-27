"""On-this-day flashbacks — photos taken on today's calendar date in past years.

Photo dates come from EXIF (DateTimeOriginal), falling back to file mtime, and
are cached to photo_dates.json so the expensive read happens once per file. To
avoid a long freeze the first morning on a large library, each call scans only
up to `scan_cap` not-yet-cached files; the rest are picked up on later days.
"""

import os
import json
import datetime

from modules.logger import log_error

try:
    from PIL import Image
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

DATE_CACHE_FILE = "photo_dates.json"
IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".bmp", ".webp", ".gif")

_cache = None


def _load_cache():
    global _cache
    if _cache is None:
        try:
            with open(DATE_CACHE_FILE) as f:
                _cache = json.load(f)
        except Exception:
            _cache = {}
    return _cache


def _save_cache():
    try:
        with open(DATE_CACHE_FILE, "w") as f:
            json.dump(_cache, f)
    except Exception as e:
        log_error(f"Failed to save photo dates: {e}")


def _exif_date(path):
    if not HAS_PIL:
        return None
    try:
        with Image.open(path) as img:
            exif = img._getexif() or {}
        for tag in (36867, 306):  # DateTimeOriginal, DateTime
            v = exif.get(tag)
            if v and len(str(v)) >= 10:
                return str(v)[:10].replace(":", "-")  # "YYYY:MM:DD" -> "YYYY-MM-DD"
    except Exception:
        pass
    return None


def _photo_date(path, mtime):
    cache = _load_cache()
    key = f"{path}|{mtime}"
    if key in cache:
        return cache[key]
    d = _exif_date(path)
    if not d:
        try:
            d = datetime.datetime.fromtimestamp(mtime).strftime("%Y-%m-%d")
        except Exception:
            d = ""
    cache[key] = d
    return d


def todays_flashbacks(files, config=None, today=None, scan_cap=3000):
    """Return [(path, year), ...] for photos dated today's month-day in prior years."""
    today = today or datetime.date.today()
    mmdd = today.strftime("%m-%d")
    cache = _load_cache()
    out = []
    scanned_new = 0

    for path in files:
        if not str(path).lower().endswith(IMAGE_EXTS):
            continue
        try:
            mtime = os.path.getmtime(path)
        except Exception:
            mtime = 0
        key = f"{path}|{mtime}"
        if key not in cache:
            if scanned_new >= scan_cap:
                continue  # defer to a later day to bound the work
            scanned_new += 1
        d = _photo_date(path, mtime)
        if d and len(d) == 10 and d[5:10] == mmdd:
            try:
                year = int(d[:4])
            except ValueError:
                continue
            if year < today.year:
                out.append((path, year))

    if scanned_new:
        _save_cache()
    return out
