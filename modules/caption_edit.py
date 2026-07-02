"""Update the stored caption for a photo, in media_log.json and (if it's a
dated greeting) scheduled_media.json. Used by the F10 on-screen editor and the
fix_caption.py CLI."""

import os
import json
import datetime

from modules.logger import log_error

_FILES = ("media_log.json", "scheduled_media.json")


def get_caption(path):
    """The most recent stored caption for `path`, or '' if none."""
    try:
        with open("media_log.json") as f:
            log = json.load(f)
    except Exception:
        return ""
    cap = ""
    for e in log:
        if isinstance(e, dict) and (e.get("file_path") or e.get("path")) == path:
            cap = e.get("caption") or cap
    return cap or ""


def update_caption(path, new_caption):
    """Set the caption for every entry referencing `path`. If media_log.json has
    no entry for it yet, one is created so the caption sticks. Returns the number
    of entries changed/created."""
    changed = 0
    for fname in _FILES:
        if os.path.exists(fname):
            try:
                with open(fname) as f:
                    data = json.load(f)
            except Exception:
                continue                      # never overwrite a corrupt file
        elif fname == "media_log.json":
            data = []                         # fine to create the log
        else:
            continue                          # no scheduled file -> nothing to do

        hit = False
        for e in data:
            if isinstance(e, dict) and (e.get("file_path") or e.get("path")) == path:
                e["caption"] = new_caption
                hit = True
                changed += 1
        if fname == "media_log.json" and not hit:
            data.append({"timestamp": datetime.datetime.now().isoformat(),
                         "file_path": path, "sender": "", "date": None,
                         "caption": new_caption})
            hit = True
            changed += 1
        if hit:
            try:
                with open(fname, "w") as f:
                    json.dump(data, f, indent=4)
            except Exception as ex:
                log_error(f"Failed to write {fname}: {ex}")
    return changed
