#!/usr/bin/env python3
"""Clean up leaderboard.json: drop bounce/system 'senders' that were counted
before the bounce filter existed, and merge renamed contributors.

    python3 fix_leaderboard.py                          # dry run (default renames)
    python3 fix_leaderboard.py --apply
    python3 fix_leaderboard.py --rename "Old Name=New Name" --apply

Built-in: removes "Mail Delivery Subsystem" & other daemon entries, and merges
"Richard Sommer" -> "Laura Sommer". Merging adds the counts together.
"""

import os
import sys
import json

os.chdir(os.path.dirname(os.path.abspath(__file__)))

LEADERBOARD_FILE = "leaderboard.json"

# Substrings that mark a non-human system sender (never a real contributor).
BOUNCE_MARKERS = ("mail delivery subsystem", "mailer-daemon", "mailer daemon",
                  "postmaster", "delivery subsystem", "no-reply", "noreply")

# name -> name merges applied to the counts.
RENAMES = {"Richard Sommer": "Laura Sommer"}


def main():
    args = sys.argv[1:]
    apply = "--apply" in args
    while "--rename" in args:
        i = args.index("--rename")
        try:
            old, new = args[i + 1].split("=", 1)
            RENAMES[old.strip()] = new.strip()
        except Exception:
            print("bad --rename (use \"Old=New\")")
            return
        del args[i:i + 2]

    try:
        data = json.load(open(LEADERBOARD_FILE))
    except Exception as e:
        print(f"Can't read {LEADERBOARD_FILE}: {e}")
        return

    result = {}
    dropped, merged = [], []
    for name, count in data.items():
        low = name.lower()
        if any(m in low for m in BOUNCE_MARKERS):
            dropped.append((name, count))
            continue
        target = RENAMES.get(name.strip(), name)
        if target != name:
            merged.append((name, target, count))
        result[target] = result.get(target, 0) + count

    print("Bounce/system entries to DROP:")
    for n, c in dropped or [("(none)", "")]:
        print(f"   - {n}  ({c})")
    print("\nRenames/merges:")
    for old, new, c in merged or [("(none)", "", "")]:
        print(f"   - {old}  ->  {new}  (+{c})")

    print("\nResulting top contributors:")
    for n, c in sorted(result.items(), key=lambda x: x[1], reverse=True)[:15]:
        print(f"   {c:>4}  {n}")

    if not apply:
        print("\n(dry run — re-run with --apply to write leaderboard.json)")
        return

    json.dump(result, open(LEADERBOARD_FILE, "w"), indent=2)
    print(f"\nWrote {LEADERBOARD_FILE} ({len(result)} contributors).")


if __name__ == "__main__":
    main()
