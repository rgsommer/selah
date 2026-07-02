#!/usr/bin/env python3
"""Fix a photo caption from the command line.

    python3 fix_caption.py "Kolby" "Colby"        # replace text in ALL captions
    python3 fix_caption.py --path media/email/RichardSommer/photo_1.jpg "New caption"
    python3 fix_caption.py --list Kolby            # show captions containing text

Same effect as the F10 on-screen editor; handy for a quick typo fix.
"""

import os
import sys
import json

os.chdir(os.path.dirname(os.path.abspath(__file__)))

from modules.caption_edit import update_caption


def _entries():
    try:
        with open("media_log.json") as f:
            return json.load(f)
    except Exception:
        return []


def main():
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return

    if args[0] == "--list":
        needle = args[1] if len(args) > 1 else ""
        for e in _entries():
            cap = (e.get("caption") or "")
            if needle.lower() in cap.lower() and cap:
                print(f"{e.get('file_path')}\n    {cap}")
        return

    if args[0] == "--path":
        if len(args) < 3:
            print("Usage: fix_caption.py --path <file> \"New caption\"")
            return
        path, new_cap = args[1], args[2]
        n = update_caption(path, new_cap)
        print(f"Updated {n} entry(ies) for {path}")
        return

    # Text replace across all captions.
    if len(args) < 2:
        print("Usage: fix_caption.py \"old text\" \"new text\"")
        return
    old, new = args[0], args[1]
    changed = 0
    for e in _entries():
        cap = e.get("caption") or ""
        if old in cap:
            n = update_caption(e.get("file_path"), cap.replace(old, new))
            if n:
                changed += 1
                print(f"  {e.get('file_path')}: {cap}  ->  {cap.replace(old, new)}")
    print(f"Fixed {changed} caption(s).")


if __name__ == "__main__":
    main()
