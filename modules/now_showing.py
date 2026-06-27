"""Tracks the photo currently on screen.

Lets other parts of the app (the web "Favorite" button, a voice "favorite
this" command) act on whatever is being displayed right now.
"""

_current = {"path": None}


def set_current(path):
    if path:
        _current["path"] = path


def get_current():
    return _current.get("path")
