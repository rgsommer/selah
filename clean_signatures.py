#!/usr/bin/env python3
"""Find and remove email-signature images (small logos/icons) that were saved as
photos: moves them to deleted/ and unschedules them, so they never render.

    python3 clean_signatures.py            # dry run — list candidates (< 500 px)
    python3 clean_signatures.py --px 400   # custom size threshold
    python3 clean_signatures.py --apply    # actually move + unschedule
"""

import os
import sys
import json
import shutil

os.chdir(os.path.dirname(os.path.abspath(__file__)))

from modules.config_utils import load_config

IMG_EXTS = (".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".heic", ".heif")


def main():
    try:
        from PIL import Image
        import modules.heif_support  # noqa: F401 (HEIC dimensions)
    except Exception as e:
        print("Pillow required:", e)
        return

    args = sys.argv[1:]
    apply = "--apply" in args
    min_px = 500
    if "--px" in args:
        try:
            min_px = int(args[args.index("--px") + 1])
        except Exception:
            pass

    cfg = load_config("display_config.json")
    email_dir = cfg.get("email_dir", "media/email")

    candidates = []
    for root, _dirs, files in os.walk(email_dir):
        for f in files:
            if not f.lower().endswith(IMG_EXTS):
                continue
            p = os.path.join(root, f)
            try:
                with Image.open(p) as im:
                    w, h = im.size
            except Exception:
                continue
            if max(w, h) < min_px:
                candidates.append((p, w, h))

    print(f"Signature-image candidates (largest side < {min_px}px) in {email_dir}:")
    for p, w, h in candidates:
        print(f"   {w}x{h}   {p}")
    print(f"\n{len(candidates)} candidate(s).")

    if not apply:
        print("(dry run — re-run with --apply to move them to deleted/ and unschedule)")
        return

    # Unschedule any of these paths.
    cand_paths = {p for p, _, _ in candidates}
    try:
        sched = json.load(open("scheduled_media.json"))
        new_sched = [e for e in sched if e.get("path") not in cand_paths]
        if len(new_sched) != len(sched):
            json.dump(new_sched, open("scheduled_media.json", "w"), indent=2)
            print(f"Unscheduled {len(sched) - len(new_sched)} entry(ies).")
    except Exception:
        pass

    trash = os.path.join(os.getcwd(), "deleted")
    os.makedirs(trash, exist_ok=True)
    moved = 0
    for p, _w, _h in candidates:
        try:
            dest = os.path.join(trash, os.path.basename(p))
            if os.path.exists(dest):
                base, ext = os.path.splitext(os.path.basename(p))
                dest = os.path.join(trash, f"{base}_{int(os.path.getmtime(p))}{ext}")
            shutil.move(p, dest)
            moved += 1
        except Exception as e:
            print(f"  couldn't move {p}: {e}")
    print(f"Moved {moved} signature image(s) to deleted/.")


if __name__ == "__main__":
    main()
