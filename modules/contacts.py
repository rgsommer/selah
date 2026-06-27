"""Family/friends contacts with optional birthdays.

Stored in contacts.json as a list of records:
  {"email": "...", "name": "...", "birthday": "MM-DD" | "YYYY-MM-DD",
   "photo_keyword": "..."}

The approved-senders whitelist (approved_senders.json) stays a flat list of
emails for fast intake checks; contacts layer the human details on top. Adding
a contact keeps the whitelist in sync. On a contact's birthday the special-day
engine celebrates them and biases the slideshow toward their photos (via
photo_keyword — derived from the email when not set).
"""

import os
import re
import json
import datetime

from modules.logger import log_error

CONTACTS_FILE = "contacts.json"
APPROVED_FILE = "approved_senders.json"


def derive_name(email):
    """Best-guess display name from an email local-part (e.g. jane.doe -> Jane Doe)."""
    local = (email or "").split("@")[0]
    return local.replace(".", " ").replace("_", " ").strip().title() or (email or "")


def derive_keyword(email):
    """Best-guess photo keyword (first token of the local-part, lowercased)."""
    local = (email or "").split("@")[0]
    first = local.replace("_", ".").split(".")[0]
    return first.strip().lower()


def load_contacts():
    """Load contacts.json, migrating from approved_senders.json on first run."""
    try:
        if os.path.exists(CONTACTS_FILE):
            with open(CONTACTS_FILE) as f:
                data = json.load(f)
            return [c for c in data if isinstance(c, dict) and c.get("email")]
    except Exception as e:
        log_error(f"Failed to load contacts: {e}")

    # First run: seed from the existing approved-senders whitelist.
    out = []
    try:
        if os.path.exists(APPROVED_FILE):
            with open(APPROVED_FILE) as f:
                for em in json.load(f):
                    em = str(em).strip()
                    if em:
                        out.append({
                            "email": em,
                            "name": derive_name(em),
                            "birthday": "",
                            "photo_keyword": derive_keyword(em),
                        })
    except Exception:
        pass
    return out


def save_contacts(contacts):
    """Persist contacts and keep the approved-senders whitelist in sync."""
    try:
        with open(CONTACTS_FILE, "w") as f:
            json.dump(contacts, f, indent=2)
    except Exception as e:
        log_error(f"Failed to save contacts: {e}")
    _sync_approved(contacts)


def _sync_approved(contacts):
    """Ensure every contact email appears in approved_senders.json (additive)."""
    try:
        approved = []
        if os.path.exists(APPROVED_FILE):
            with open(APPROVED_FILE) as f:
                approved = [str(s).strip() for s in json.load(f) if str(s).strip()]
        changed = False
        for c in contacts:
            em = (c.get("email") or "").strip()
            if em and em not in approved:
                approved.append(em)
                changed = True
        if changed:
            with open(APPROVED_FILE, "w") as f:
                json.dump(approved, f, indent=2)
    except Exception as e:
        log_error(f"Failed to sync approved senders: {e}")


_BDAY_FORMATS = [
    "%m-%d", "%Y-%m-%d", "%m/%d", "%m/%d/%Y",
    "%b %d", "%B %d", "%b %d %Y", "%B %d %Y",
    "%d %b", "%d %B",
]


def parse_birthday(text):
    """Parse flexible date input into 'MM-DD' (or 'YYYY-MM-DD' if a year given).

    Accepts e.g. "09-04", "Sept 4", "September 4 1960", "9/4". Returns "" if
    it can't be understood.
    """
    text = (text or "").strip().replace(".", "").replace(",", "")
    if not text:
        return ""
    # "Sept" -> "Sep" (Python's %b wants the 3-letter form).
    text = re.sub(r"\bSept\b", "Sep", text, flags=re.IGNORECASE)
    # Drop ordinal suffixes: "4th" -> "4", "1st" -> "1".
    text = re.sub(r"\b(\d{1,2})(st|nd|rd|th)\b", r"\1", text, flags=re.IGNORECASE)
    for fmt in _BDAY_FORMATS:
        try:
            dt = datetime.datetime.strptime(text, fmt)
            return dt.strftime("%Y-%m-%d") if "%Y" in fmt else dt.strftime("%m-%d")
        except ValueError:
            continue
    return ""


def todays_birthday_contacts(today=None):
    """Contacts whose birthday is today (year-agnostic match)."""
    today = today or datetime.date.today()
    mmdd = today.strftime("%m-%d")
    out = []
    for c in load_contacts():
        b = str(c.get("birthday", "")).strip()
        if b and (b == mmdd or b.endswith("-" + mmdd)):
            out.append(c)
    return out
