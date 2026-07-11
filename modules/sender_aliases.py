"""Per-email display-name overrides.

Some accounts send under a name that isn't the person you want shown — e.g. a
shared Gmail whose From header still says "Richard Sommer" but is really Laura's.
Map the email address to the preferred name in ``sender_aliases.json`` and every
display path (leaderboard, the '— from <Name>' caption, approval requests) uses
it instead of the raw From name.

    {
      "pngsommers@gmail.com": "Laura Sommer"
    }

The file is untracked (may contain personal emails); see sender_aliases.example.json.
"""

import json
from email.utils import parseaddr

ALIAS_FILE = "sender_aliases.json"
_cache = None


def _load():
    global _cache
    if _cache is None:
        try:
            with open(ALIAS_FILE) as f:
                _cache = {str(k).lower().strip(): v for k, v in json.load(f).items()}
        except Exception:
            _cache = {}
    return _cache


def alias_for(sender):
    """Preferred display name for a sender's email address, or None if unset.

    ``sender`` may be a full header ("Name <a@b.com>") or a bare address.
    """
    _, addr = parseaddr(sender or "")
    if not addr and sender and "@" in sender:
        addr = sender.strip()
    if not addr:
        return None
    return _load().get(addr.lower().strip())
