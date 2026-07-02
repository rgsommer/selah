"""A tiny thread-safe queue of just-arrived photo paths.

The email checker runs inside the main loop but without access to the render
state, so when a new submission is saved it drops the path here; the main loop
drains it each tick and surfaces the photo at the very next rotation.
"""

import threading

_lock = threading.Lock()
_pending = []


def add(path):
    """Record a newly-saved photo to be shown at the next rotation."""
    if not path:
        return
    with _lock:
        if path not in _pending:
            _pending.append(path)


def take_all():
    """Return and clear all pending photo paths."""
    with _lock:
        items = _pending[:]
        _pending.clear()
    return items
