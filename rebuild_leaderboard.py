#!/usr/bin/env python3
"""Rebuild leaderboard.json from media_log.json — the source of truth for every
submission, email AND QR/phone upload. This backfills contributors that were
logged before the leaderboard counted them (e.g. past QR uploads), drops
bounce/system 'senders', and applies sender_aliases.json + name renames.

    python3 rebuild_leaderboard.py            # dry run — show the rebuilt board
    python3 rebuild_leaderboard.py --apply
"""

import os
import sys
import json
from email.utils import parseaddr

os.chdir(os.path.dirname(os.path.abspath(__file__)))

LEADERBOARD_FILE = "leaderboard.json"
MEDIA_LOG = "media_log.json"

BOUNCE_MARKERS = ("mail delivery subsystem", "mailer-daemon", "mailer daemon",
                  "postmaster", "delivery subsystem", "no-reply", "noreply")
SKIP_NAMES = {"visitor", "unknown", ""}
RENAMES = {"Richard Sommer": "Laura Sommer"}


def resolve_name(sender):
    """Preferred display name for a media_log 'sender' (email header or bare name)."""
    s = (sender or "").strip()
    if any(m in s.lower() for m in BOUNCE_MARKERS):
        return None
    try:
        from modules.sender_aliases import alias_for
        name = alias_for(s)
    except Exception:
        name = None
    if not name:
        nm, addr = parseaddr(s)
        name = (nm or "").strip().strip('"').strip("'")
        if not name:
            name = s.split("<")[0].strip() or (addr or "")
    name = RENAMES.get(name.strip(), name).strip()
    return None if name.lower() in SKIP_NAMES else name


def main():
    apply = "--apply" in sys.argv
    try:
        log = json.load(open(MEDIA_LOG))
    except Exception as e:
        print(f"Can't read {MEDIA_LOG}: {e}")
        return

    tally = {}
    seen_files = set()
    counted = skipped = 0
    for e in log:
        fp = e.get("file_path")
        if fp:                                   # count each photo once
            if fp in seen_files:
                continue
            seen_files.add(fp)
        name = resolve_name(e.get("sender", ""))
        if not name:
            skipped += 1
            continue
        tally[name] = tally.get(name, 0) + 1
        counted += 1

    print(f"Scanned {len(log)} log entries -> {counted} counted, "
          f"{skipped} skipped (bounce/anonymous).\n")
    print("Rebuilt leaderboard:")
    for n, c in sorted(tally.items(), key=lambda x: x[1], reverse=True):
        print(f"   {c:>4}  {n}")

    # Show what changes vs the current board.
    try:
        cur = json.load(open(LEADERBOARD_FILE))
    except Exception:
        cur = {}
    added = [n for n in tally if n not in cur]
    if added:
        print("\nNewly credited (were missing):")
        for n in added:
            print(f"   + {n} ({tally[n]})")

    if not apply:
        print("\n(dry run — re-run with --apply to write leaderboard.json)")
        return
    json.dump(tally, open(LEADERBOARD_FILE, "w"), indent=2)
    print(f"\nWrote {LEADERBOARD_FILE} ({len(tally)} contributors).")


if __name__ == "__main__":
    main()
