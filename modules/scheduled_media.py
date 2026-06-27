"""Dated greetings that display on a specific day.

A photo whose filename (or email subject) carries a date — e.g.
"Happy Birthday, Mom Sept 4.jpg" — is scheduled here instead of going into the
normal rotation. It then appears on that day:
  * recurring=True  -> every year on its MM-DD (indefinitely)
  * recurring=False -> only on the next occurrence (one year)

Stored in scheduled_media.json as a list of:
  {"path", "mmdd", "target" (YYYY-MM-DD), "recurring", "caption"}
"""

import os
import re
import json
import datetime

from modules.logger import log_error

SCHEDULED_FILE = "scheduled_media.json"

_MONTHS = ("jan|feb|mar|apr|may|jun|jul|aug|sept|sep|oct|nov|dec|january|february|"
           "march|april|june|july|august|september|october|november|december")


def load_scheduled():
    try:
        with open(SCHEDULED_FILE) as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception:
        return []


def save_scheduled(items):
    try:
        with open(SCHEDULED_FILE, "w") as f:
            json.dump(items, f, indent=2)
    except Exception as e:
        log_error(f"Failed to save scheduled media: {e}")


def parse_filename(name):
    """Extract (mmdd, iso_or_'', caption) from a filename; mmdd None if no date."""
    base = os.path.splitext(os.path.basename(str(name)))[0]

    # YYYY-MM-DD
    m = re.search(r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})", base)
    if m:
        try:
            d = datetime.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            cap = (base[:m.start()] + base[m.end():]).strip(" ,-_")
            return d.strftime("%m-%d"), d.isoformat(), cap
        except Exception:
            pass

    # Month Day  (e.g. "Sept 4")
    m = re.search(r"\b(" + _MONTHS + r")\s+(\d{1,2})\b", base, re.IGNORECASE)
    if m:
        try:
            from modules.contacts import parse_birthday
            mmdd = parse_birthday(f"{m.group(1)} {m.group(2)}")
        except Exception:
            mmdd = ""
        if mmdd:
            cap = (base[:m.start()] + base[m.end():]).strip(" ,-_")
            return mmdd, "", cap

    # MM-DD or M/D
    m = re.search(r"\b(\d{1,2})[-/](\d{1,2})\b", base)
    if m:
        mo, da = int(m.group(1)), int(m.group(2))
        if 1 <= mo <= 12 and 1 <= da <= 31:
            cap = (base[:m.start()] + base[m.end():]).strip(" ,-_")
            return f"{mo:02d}-{da:02d}", "", cap

    return None, "", base


def add_scheduled(path, mmdd, caption="", recurring=True, target_iso="", today=None):
    """Record a dated greeting. No-op if already present. Returns True if added."""
    items = load_scheduled()
    if any(i.get("path") == path for i in items):
        return False
    today = today or datetime.date.today()

    if not target_iso:
        try:
            mo, da = int(mmdd[:2]), int(mmdd[3:5])
            tgt = datetime.date(today.year, mo, da)
            if tgt < today:
                tgt = datetime.date(today.year + 1, mo, da)
            target_iso = tgt.isoformat()
        except Exception:
            target_iso = ""

    items.append({
        "path": path, "mmdd": mmdd, "target": target_iso,
        "recurring": bool(recurring), "caption": caption,
    })
    save_scheduled(items)
    return True


def scheduled_paths():
    """All scheduled paths (to exclude from the normal rotation)."""
    return {i.get("path") for i in load_scheduled() if i.get("path")}


def todays_scheduled(today=None):
    """Scheduled greetings that should display today."""
    today = today or datetime.date.today()
    mmdd = today.strftime("%m-%d")
    iso = today.isoformat()
    out = []
    for i in load_scheduled():
        if not os.path.exists(i.get("path", "")):
            continue
        if i.get("recurring"):
            if i.get("mmdd") == mmdd:
                out.append(i)
        elif i.get("target") == iso:
            out.append(i)
    return out
