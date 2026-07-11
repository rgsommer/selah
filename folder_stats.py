#!/usr/bin/env python3
"""Audit every media folder: how many eligible photos/videos it holds, how many
actually reach the rotation, and — importantly — flag any folder with eligible
files that is NOT being reached, so you have assurance nothing is missed.

    python3 folder_stats.py
    python3 folder_stats.py --all     # also list every folder, not just problems
"""

import os
import sys
import json
from collections import defaultdict

os.chdir(os.path.dirname(os.path.abspath(__file__)))

from modules.config_utils import load_config


def norm(p):
    return os.path.normcase(os.path.abspath(p))


def main():
    show_all = "--all" in sys.argv
    cfg = load_config("display_config.json")

    from modules.image_loader import get_images_and_videos, photo_dims
    try:
        from modules.scheduled_media import scheduled_paths
        scheduled = {norm(p) for p in scheduled_paths()}
    except Exception:
        scheduled = set()

    # What the slideshow actually loads right now.
    portrait, landscape = get_images_and_videos(cfg)
    reached = {norm(p) for p in list(portrait) + list(landscape)}

    valid_ext = tuple(e.lower() for e in cfg.get(
        "valid_extensions", [".jpg", ".jpeg", ".png", ".mp4", ".avi", ".mov"]))
    image_ext = (".jpg", ".jpeg", ".png", ".bmp", ".gif", ".webp", ".heic", ".heif")
    video_ext = (".mp4", ".avi", ".mov")
    videos_on = cfg.get("videos_enabled", True)
    privacy_on = cfg.get("privacy_mode_enabled", False)
    private_tokens = [str(t).lower() for t in cfg.get("private_dirs", ["private"])]
    min_px = int(cfg.get("min_photo_px", 0) or 0)

    media_folder = cfg.get("media_folder", "media")
    # Roots to WALK (audit the whole tree; the scanner in 'separate' mode only
    # visits specific sub-roots, which is the thing we're checking).
    roots = {media_folder}
    for k in ("portrait_dir", "landscape_dir", "art_dir", "display_dir",
              "drive_pull_dir", "email_dir"):
        roots.add(cfg.get(k, ""))
    roots = [r for r in roots if r and os.path.isdir(r)]

    # folder -> counters
    stats = defaultdict(lambda: {"total": 0, "reached": 0, "held": 0,
                                 "excluded": 0, "missed": 0, "miss_ex": []})
    seen = set()

    def classify_excluded(p, ext):
        low = p.lower()
        if privacy_on and any(t in low for t in private_tokens):
            return "private"
        if ext in video_ext and not videos_on:
            return "video-off"
        if ext in image_ext:
            try:
                _, edge = photo_dims(p)
            except Exception:
                edge = -1
            if edge == 0:
                return "corrupt"
            if min_px and 0 < edge < min_px:
                return "tiny"
        return None

    for root in roots:
        for dirpath, _dirs, files in os.walk(root):
            for f in files:
                if not f.lower().endswith(valid_ext):
                    continue
                p = os.path.join(dirpath, f)
                n = norm(p)
                if n in seen:
                    continue
                seen.add(n)
                folder = os.path.relpath(dirpath)
                s = stats[folder]
                s["total"] += 1
                if n in reached:
                    s["reached"] += 1
                elif n in scheduled:
                    s["held"] += 1
                else:
                    why = classify_excluded(p, os.path.splitext(f)[1].lower())
                    if why:
                        s["excluded"] += 1
                    else:
                        s["missed"] += 1
                        if len(s["miss_ex"]) < 2:
                            s["miss_ex"].append(f)

    tot = {k: sum(s[k] for s in stats.values())
           for k in ("total", "reached", "held", "excluded", "missed")}

    print(f"media_mode = {cfg.get('media_mode', 'separate')}   "
          f"(hide_blurry={cfg.get('hide_blurry_enabled', False)}, "
          f"privacy={privacy_on}, videos={videos_on})\n")

    missed_folders = sorted((k for k, s in stats.items() if s["missed"]), key=str.lower)
    if missed_folders:
        print("⚠  FOLDERS WITH FILES NOT REACHING THE ROTATION:")
        for k in missed_folders:
            s = stats[k]
            eg = f"  e.g. {', '.join(s['miss_ex'])}" if s["miss_ex"] else ""
            print(f"   {k}   {s['missed']} of {s['total']} not reached{eg}")
        print("   -> move these under a scanned folder (media/display, media/landscape,")
        print("      media/portrait, media/art) or add the folder as a source.\n")
    else:
        print("✅ Every eligible file in every folder is reached (or held/excluded on purpose).\n")

    if show_all:
        print("All folders (eligible / reached / held / excluded / MISSED):")
        for k in sorted(stats, key=str.lower):
            s = stats[k]
            flag = "  ⚠" if s["missed"] else ""
            print(f"   {k:<44} {s['total']:>5}  r{s['reached']} h{s['held']} "
                  f"x{s['excluded']} m{s['missed']}{flag}")
        print()

    print("Totals:")
    print(f"  eligible files ......... {tot['total']}")
    print(f"  reaching rotation ...... {tot['reached']}")
    print(f"  held (scheduled) ....... {tot['held']}")
    print(f"  excluded (private/corrupt/tiny/video-off) ... {tot['excluded']}")
    print(f"  NOT reached ............ {tot['missed']}"
          + ("   ⚠ see folders above" if tot['missed'] else ""))


if __name__ == "__main__":
    main()
