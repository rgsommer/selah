"""Blur detection — optionally hide out-of-focus photos.

Uses OpenCV's variance-of-Laplacian as a sharpness score, cached to disk so the
expensive read happens once per file. Scans at most `scan_cap` new files per
call so a big library doesn't freeze on the first pass; unscanned files are
kept (shown) until evaluated.
"""

import os
import json

from modules.logger import log_error

try:
    import cv2
    HAS_CV2 = True
except Exception:
    HAS_CV2 = False

QUALITY_CACHE_FILE = "quality_cache.json"
IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".bmp", ".webp")

_cache = None


def _load():
    global _cache
    if _cache is None:
        try:
            with open(QUALITY_CACHE_FILE) as f:
                _cache = json.load(f)
        except Exception:
            _cache = {}
    return _cache


def _save():
    try:
        with open(QUALITY_CACHE_FILE, "w") as f:
            json.dump(_cache, f)
    except Exception as e:
        log_error(f"Failed to save quality cache: {e}")


def _sharpness(path):
    try:
        img = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
        if img is None:
            return None
        return float(cv2.Laplacian(img, cv2.CV_64F).var())
    except Exception:
        return None


def filter_sharp(files, config, scan_cap=2000):
    """Drop images whose sharpness is below blur_threshold. No-op unless enabled."""
    if not config.get("hide_blurry_enabled", False) or not HAS_CV2 or not files:
        return files
    threshold = float(config.get("blur_threshold", 60))
    cache = _load()
    out = []
    scanned = 0
    for f in files:
        if not str(f).lower().endswith(IMAGE_EXTS):
            out.append(f)
            continue
        try:
            mt = os.path.getmtime(f)
        except Exception:
            mt = 0
        key = f"{f}|{mt}"
        if key in cache:
            s = cache[key]
        elif scanned >= scan_cap:
            out.append(f)  # not yet evaluated -> keep it
            continue
        else:
            s = _sharpness(f)
            cache[key] = s
            scanned += 1
        if s is None or s >= threshold:
            out.append(f)
    if scanned:
        _save()
    return out
