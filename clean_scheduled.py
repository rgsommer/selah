#!/usr/bin/env python3
"""Tidy scheduled_media.json:
  - drop mis-parsed 'Month YYYY' album-label entries (e.g. 'June 2026', which the
    old parser wrongly scheduled as a Month-20 greeting),
  - re-clean captions so a trailing date is stripped ('… Sept 4' -> '…'),
  - remove duplicate greetings (same date + caption).
Backs up to scheduled_media.json.bak first.

    python3 clean_scheduled.py            # show what it would do
    python3 clean_scheduled.py --apply    # actually write the changes
"""

import os
import re
import sys
import json

os.chdir(os.path.dirname(os.path.abspath(__file__)))

from modules.email_handler import _subject_caption

PATH = "scheduled_media.json"
MONTH_YEAR = re.compile(
    r"^\s*(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+(?:19|20)\d{2}\s*$",
    re.I)


def main():
    apply = "--apply" in sys.argv
    try:
        items = json.load(open(PATH))
    except Exception as e:
        print(f"Can't read {PATH}: {e}")
        return

    kept, dropped_junk, dropped_dup, recap = [], [], 0, 0
    seen = set()
    for e in items:
        cap = e.get("caption", "") or ""
        if MONTH_YEAR.match(cap):                 # album label mis-scheduled
            dropped_junk.append((e.get("mmdd"), cap))
            continue
        new = _subject_caption(cap)
        if new != cap:
            e["caption"] = new
            recap += 1
        key = (e.get("mmdd"), e.get("caption"))
        if key in seen:
            dropped_dup += 1
            continue
        seen.add(key)
        kept.append(e)

    print(f"scheduled greetings: {len(items)} -> {len(kept)}")
    print(f"  drop {len(dropped_junk)} 'Month YYYY' album-label entries "
          + (f"(e.g. {dropped_junk[0][1]!r})" if dropped_junk else ""))
    print(f"  drop {dropped_dup} duplicate(s)")
    print(f"  clean {recap} caption(s) (strip trailing date)")

    if not apply:
        print("\n(dry run — re-run with --apply to write; backup is made automatically)")
        return
    try:
        json.dump(items, open(PATH + ".bak", "w"), indent=2)
    except Exception:
        pass
    json.dump(kept, open(PATH, "w"), indent=2)
    print(f"\nApplied. Backup: {PATH}.bak")


if __name__ == "__main__":
    main()
