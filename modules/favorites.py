"""Favorited photos — shown more often when favorites_boost_enabled.

Family can favorite the on-screen photo from the web dashboard; favorites are
stored in favorites.json and interleaved into the rotation more frequently.
"""

import json

from modules.logger import log_error

FAVORITES_FILE = "favorites.json"


def load_favorites():
    try:
        with open(FAVORITES_FILE) as f:
            data = json.load(f)
        return [str(p) for p in data] if isinstance(data, list) else []
    except Exception:
        return []


def save_favorites(favs):
    try:
        with open(FAVORITES_FILE, "w") as f:
            json.dump(favs, f, indent=2)
    except Exception as e:
        log_error(f"Failed to save favorites: {e}")


def add_favorite(path):
    if not path:
        return False
    favs = load_favorites()
    if path in favs:
        return False
    favs.append(path)
    save_favorites(favs)
    return True


def remove_favorite(path):
    favs = load_favorites()
    if path in favs:
        favs.remove(path)
        save_favorites(favs)
        return True
    return False


def prioritize_favorites(files, config):
    """Interleave favorited files more frequently. No-op unless enabled."""
    if not config.get("favorites_boost_enabled", False) or not files:
        return files
    favs = set(load_favorites())
    if not favs:
        return files
    boosted = [f for f in files if f in favs]
    if not boosted:
        return files
    # Keep every photo once, then interleave EXTRA copies of favorites so they
    # genuinely appear more often (not just repositioned).
    out = []
    interval = max(1, len(files) // (len(boosted) + 1))
    bi = 0
    for i, f in enumerate(files):
        out.append(f)
        if bi < len(boosted) and (i + 1) % interval == 0:
            out.append(boosted[bi])
            bi += 1
    out.extend(boosted[bi:])
    return out
